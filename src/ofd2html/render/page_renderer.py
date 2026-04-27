"""Render one parsed OFD page into an SVG element string.

This is intentionally a *single-pass* recursive walk over the page DOM. The
mental model:

* The SVG ``viewBox`` matches the OFD ``PhysicalBox`` (millimetres).
* For every ``GraphicUnit`` (PathObject / TextObject / ImageObject), we emit
  an SVG group with ``transform="translate(bx by) matrix(a b c d e f)"`` so
  that local coordinates inside the object map to page coordinates the same
  way an OFD reader would interpret them.
* Text is emitted as plain ``<text>`` elements -- we rely on the browser's
  font fallback rather than rasterising glyphs from embedded fonts. This is
  the documented "fallback path 2" in the refactor plan.
"""

from __future__ import annotations

import base64
from typing import Iterable, Optional
from xml.sax.saxutils import escape, quoteattr

from lxml import etree

from ..gv import NSMAP
from ..reader.ofd_reader import Box, Document, OFDReader, PageRef
from .color import parse_color
from .path import abbr_data_to_svg_d


# --------------------------------------------------------------------------- #
# Public entry point.
# --------------------------------------------------------------------------- #


def render_page_to_svg(reader: OFDReader, doc: Document, page: PageRef) -> str:
    """Return a complete ``<svg>...</svg>`` string for ``page``."""
    page_el = reader.page_content(doc, page)
    box = (
        Box.parse(_xpath_text(page_el, ".//ofd:Area/ofd:PhysicalBox"))
        or doc.physical_box
    )
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {_num(box.w)} {_num(box.h)}" '
        f'width="{_num(box.w)}mm" height="{_num(box.h)}mm" '
        f'style="background:#fff;display:block;">'
    )
    # Walk all layers in document order.
    for layer in page_el.findall(".//ofd:Content/ofd:Layer", NSMAP):
        for child in layer:
            _render_node(child, reader, doc, parts)
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Recursive renderer.
# --------------------------------------------------------------------------- #


def _render_node(
    node: etree._Element,
    reader: OFDReader,
    doc: Document,
    out: list[str],
) -> None:
    tag = etree.QName(node).localname
    if tag == "PageBlock":
        for child in node:
            _render_node(child, reader, doc, out)
    elif tag == "PathObject":
        out.append(_render_path_object(node))
    elif tag == "TextObject":
        out.append(_render_text_object(node))
    elif tag == "ImageObject":
        out.append(_render_image_object(node, reader, doc))
    # Unknown nodes are silently skipped so future OFD features
    # don't break the whole page.


# --------------------------------------------------------------------------- #
# PathObject.
# --------------------------------------------------------------------------- #


def _render_path_object(node: etree._Element) -> str:
    boundary = Box.parse(node.get("Boundary"))
    ctm = node.get("CTM")
    fill_attr = (node.get("Fill") or "").lower()
    stroke_attr = (node.get("Stroke") or "").lower()
    line_width = node.get("LineWidth") or "0.353"

    # OFD defaults: when neither Fill nor Stroke is given on a PathObject the
    # spec defaults Stroke=true.
    do_fill = fill_attr == "true"
    do_stroke = stroke_attr == "true" or (fill_attr == "" and stroke_attr == "")

    fill_color = (
        parse_color(_xpath_attr(node, "ofd:FillColor", "Value"), "#000000")
        if do_fill
        else "none"
    )
    stroke_color = (
        parse_color(_xpath_attr(node, "ofd:StrokeColor", "Value"), "#000000")
        if do_stroke
        else "none"
    )

    abbr = _xpath_text(node, "ofd:AbbreviatedData") or ""
    d_attr = abbr_data_to_svg_d(abbr)
    if not d_attr:
        return ""

    transform = _build_transform(boundary, ctm)
    attrs = [f"d={quoteattr(d_attr)}"]
    if fill_color != "none":
        attrs.append(f'fill="{fill_color}"')
    else:
        attrs.append('fill="none"')
    if stroke_color != "none":
        attrs.append(f'stroke="{stroke_color}"')
        attrs.append(f'stroke-width="{line_width}"')
    if transform:
        attrs.append(f'transform="{transform}"')
    return "<path " + " ".join(attrs) + "/>"


# --------------------------------------------------------------------------- #
# TextObject.
# --------------------------------------------------------------------------- #


def _render_text_object(node: etree._Element) -> str:
    boundary = Box.parse(node.get("Boundary"))
    ctm = node.get("CTM")
    size_raw = node.get("Size") or "3"
    try:
        size = float(size_raw)
    except ValueError:
        size = 3.0
    weight = node.get("Weight") or ""
    italic = (node.get("Italic") or "").lower() == "true"

    fill_color = parse_color(_xpath_attr(node, "ofd:FillColor", "Value"), "#000000")

    transform = _build_transform(boundary, ctm)

    out: list[str] = []
    for tc in node.findall("ofd:TextCode", NSMAP):
        text = tc.text or ""
        if not text:
            continue
        try:
            x0 = float(tc.get("X") or "0")
            y0 = float(tc.get("Y") or "0")
        except ValueError:
            continue
        delta_x = _parse_deltas(tc.get("DeltaX"))
        delta_y = _parse_deltas(tc.get("DeltaY"))

        # Build absolute x/y lists from deltas (OFD: each delta is the advance
        # *between* successive characters).
        xs: list[float] = [x0]
        ys: list[float] = [y0]
        for ch_index in range(1, len(text)):
            dx = delta_x[ch_index - 1] if ch_index - 1 < len(delta_x) else 0.0
            dy = delta_y[ch_index - 1] if ch_index - 1 < len(delta_y) else 0.0
            xs.append(xs[-1] + dx)
            ys.append(ys[-1] + dy)

        attrs = [
            f'x="{" ".join(_num(v) for v in xs)}"',
            f'y="{" ".join(_num(v) for v in ys)}"',
            f'font-size="{_num(size)}"',
            f'fill="{fill_color}"',
            "font-family=\"SimSun, 'Microsoft YaHei', 'Noto Sans CJK SC', serif\"",
        ]
        if weight and weight not in ("400", "normal"):
            attrs.append(f'font-weight="{escape(weight)}"')
        if italic:
            attrs.append('font-style="italic"')
        if transform:
            attrs.append(f'transform="{transform}"')
        out.append(f"<text {' '.join(attrs)}>{escape(text)}</text>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# ImageObject.
# --------------------------------------------------------------------------- #


def _render_image_object(node: etree._Element, reader: OFDReader, doc: Document) -> str:
    res_id = node.get("ResourceID") or ""
    if not res_id:
        return ""
    media = reader.media(doc, res_id)
    if media is None:
        return ""
    try:
        data = reader.read_media(doc, res_id)
    except FileNotFoundError:
        return ""
    if data is None:
        return ""
    mime = _sniff_mime(media.file_path, data)
    href = "data:{0};base64,{1}".format(mime, base64.b64encode(data).decode("ascii"))

    # An OFD ImageObject draws its source over the unit square (0,0)-(1,1),
    # mapped to the page by Boundary + CTM. We therefore emit an <image>
    # filling the unit square and let the transform place it.
    boundary = Box.parse(node.get("Boundary"))
    ctm = node.get("CTM")
    transform = _build_transform(boundary, ctm)

    return (
        f'<image x="0" y="0" width="1" height="1" '
        f'preserveAspectRatio="none" '
        f"xlink:href={quoteattr(href)} "
        f'transform="{transform}"/>'
    )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _build_transform(boundary: Optional[Box], ctm: Optional[str]) -> str:
    parts: list[str] = []
    if boundary is not None:
        parts.append(f"translate({_num(boundary.x)} {_num(boundary.y)})")
    if ctm:
        nums = ctm.replace(",", " ").split()
        if len(nums) >= 6:
            try:
                a = " ".join(_num(float(n)) for n in nums[:6])
                parts.append(f"matrix({a})")
            except ValueError:
                pass
    return " ".join(parts)


def _parse_deltas(raw: Optional[str]) -> list[float]:
    """Parse OFD ``DeltaX``/``DeltaY``. May contain ``g`` repeat operator
    e.g. ``g 3 12.5`` -> ``[12.5, 12.5, 12.5]`` (count then value)."""
    if not raw:
        return []
    tokens = raw.replace(",", " ").split()
    out: list[float] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "g" and i + 2 < len(tokens):
            try:
                count = int(float(tokens[i + 1]))
                value = float(tokens[i + 2])
            except ValueError:
                i += 1
                continue
            out.extend([value] * count)
            i += 3
            continue
        try:
            out.append(float(tok))
        except ValueError:
            pass
        i += 1
    return out


def _xpath_text(node: etree._Element, xpath: str) -> Optional[str]:
    el = node.find(xpath, NSMAP)
    if el is None:
        return None
    return (el.text or "").strip() or None


def _xpath_attr(node: etree._Element, xpath: str, attr: str) -> Optional[str]:
    el = node.find(xpath, NSMAP)
    if el is None:
        return None
    return el.get(attr)


def _num(v: float) -> str:
    """Format a float compactly for SVG (strip trailing zeros)."""
    if isinstance(v, int):
        return str(v)
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _sniff_mime(file_path: str, data: bytes) -> str:
    lower = file_path.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".bmp"):
        return "image/bmp"
    # Magic-byte fallbacks.
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "application/octet-stream"


# Keep type-checker happy: Iterable is referenced indirectly elsewhere.
_ = Iterable

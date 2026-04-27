"""High-level OFD reader: parses OFD.xml + Document.xml + per-page Content.xml.

Designed for the HTML export pipeline only -- enough structure to render the
page contents to SVG. We keep the parsed forms as light dataclasses since
rendering is the only consumer here.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree

from ..gv import NSMAP
from ..pkg.container import OFDContainer
from .resource_locator import ResourceLocator


# --------------------------------------------------------------------------- #
# Light value objects.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Box:
    """OFD ``ST_Box`` value: x, y, w, h in millimetres."""

    x: float
    y: float
    w: float
    h: float

    @classmethod
    def parse(cls, raw: Optional[str]) -> Optional["Box"]:
        if not raw:
            return None
        parts = raw.replace(",", " ").split()
        if len(parts) != 4:
            return None
        return cls(*(float(p) for p in parts))


@dataclass
class PageRef:
    """A pointer to one page's Content.xml inside the container."""

    page_id: str
    base_loc: str  # absolute virtual path


@dataclass
class MediaRes:
    res_id: str
    media_type: str  # "Image" / "Sound" / ...
    file_path: str  # absolute virtual path resolved against res base


@dataclass
class Document:
    physical_box: Box
    pages: list[PageRef] = field(default_factory=list)
    medias: dict[str, MediaRes] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Reader.
# --------------------------------------------------------------------------- #


class OFDReader:
    """Read an OFD container and expose per-page content trees."""

    def __init__(self, ofd_bytes: bytes) -> None:
        self._container = OFDContainer(ofd_bytes)
        self._locator = ResourceLocator(self._container, cwd="/")
        self._documents: list[Document] = self._load_documents()

    # ----- public API -------------------------------------------------------

    @property
    def documents(self) -> list[Document]:
        return self._documents

    def page_content(self, doc: Document, page: PageRef) -> etree._Element:
        """Return the parsed ``<ofd:Page>`` root for one page."""
        del doc  # currently unused, but kept for future multi-doc routing
        xml = self._container.read(page.base_loc.lstrip("/"))
        return etree.fromstring(xml)

    def read_media(self, doc: Document, res_id: str) -> Optional[bytes]:
        media = doc.medias.get(res_id)
        if media is None:
            return None
        return self._container.read(media.file_path.lstrip("/"))

    def media(self, doc: Document, res_id: str) -> Optional[MediaRes]:
        return doc.medias.get(res_id)

    def close(self) -> None:
        self._container.close()

    def __enter__(self) -> "OFDReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----- loading ----------------------------------------------------------

    def _load_documents(self) -> list[Document]:
        if not self._container.has("OFD.xml"):
            raise ValueError("invalid OFD: missing OFD.xml")
        ofd_root = etree.fromstring(self._container.read("OFD.xml"))
        documents: list[Document] = []
        for doc_body in ofd_root.findall("ofd:DocBody", NSMAP):
            doc_root_el = doc_body.find("ofd:DocRoot", NSMAP)
            if doc_root_el is None or not doc_root_el.text:
                continue
            doc_root_path = self._locator.resolve(doc_root_el.text.strip())
            documents.append(self._load_document(doc_root_path))
        if not documents:
            raise ValueError("invalid OFD: no DocBody/DocRoot found")
        return documents

    def _load_document(self, doc_root_path: str) -> Document:
        doc_xml = self._container.read(doc_root_path)
        doc_el = etree.fromstring(doc_xml)
        doc_dir = posixpath.dirname("/" + doc_root_path)

        # Page area.
        physical_box = Box.parse(
            _text(doc_el, ".//ofd:CommonData/ofd:PageArea/ofd:PhysicalBox")
        ) or Box(0, 0, 210, 297)

        # Pages list.
        pages: list[PageRef] = []
        for page_el in doc_el.findall(".//ofd:Pages/ofd:Page", NSMAP):
            base_loc = page_el.get("BaseLoc") or ""
            if not base_loc:
                continue
            pages.append(
                PageRef(
                    page_id=page_el.get("ID") or "",
                    base_loc=_join_doc(doc_dir, base_loc),
                )
            )

        # Resources (PublicRes + DocumentRes). Each entry can declare
        # ``BaseLoc`` to relocate sub-files relative to the resource file.
        medias: dict[str, MediaRes] = {}
        for tag in ("ofd:PublicRes", "ofd:DocumentRes"):
            for res_el in doc_el.findall(f".//ofd:CommonData/{tag}", NSMAP):
                if not res_el.text:
                    continue
                res_path = _join_doc(doc_dir, res_el.text.strip())
                self._collect_medias(res_path, medias)

        return Document(physical_box=physical_box, pages=pages, medias=medias)

    def _collect_medias(self, res_path: str, sink: dict[str, MediaRes]) -> None:
        if not self._container.has(res_path.lstrip("/")):
            return
        res_el = etree.fromstring(self._container.read(res_path.lstrip("/")))
        res_dir = posixpath.dirname(res_path)
        # ``BaseLoc`` on <ofd:Res> further roots subsequent file refs.
        base_loc = res_el.get("BaseLoc") or ""
        media_dir = (
            posixpath.normpath(posixpath.join(res_dir, base_loc))
            if base_loc
            else res_dir
        )
        if not media_dir.startswith("/"):
            media_dir = "/" + media_dir

        for mm in res_el.findall(".//ofd:MultiMedias/ofd:MultiMedia", NSMAP):
            res_id = mm.get("ID")
            if not res_id:
                continue
            mfile_el = mm.find("ofd:MediaFile", NSMAP)
            if mfile_el is None or not mfile_el.text:
                continue
            file_path = posixpath.normpath(
                posixpath.join(media_dir, mfile_el.text.strip())
            )
            if not file_path.startswith("/"):
                file_path = "/" + file_path
            sink[res_id] = MediaRes(
                res_id=res_id,
                media_type=mm.get("Type") or "Image",
                file_path=file_path,
            )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _text(node: etree._Element, xpath: str) -> Optional[str]:
    el = node.find(xpath, NSMAP)
    if el is None:
        return None
    return (el.text or "").strip() or None


def _join_doc(doc_dir: str, rel: str) -> str:
    """Resolve a path that may be absolute (``/Doc_0/...``) or relative
    to the directory of Document.xml."""
    if rel.startswith("/"):
        return posixpath.normpath(rel)
    return posixpath.normpath(posixpath.join(doc_dir, rel))

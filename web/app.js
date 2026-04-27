// Pyodide bootstrap + ofd2html runner.
//
// Strategy: load Pyodide from CDN, install lxml from Pyodide's repo,
// then micropip-install the locally built ofd2html wheel with deps=False
// (we don't need fastapi/uvicorn/pydantic in the browser).

const PYODIDE_INDEX = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
// CI writes wheel.txt containing the actual PEP-427 wheel filename
// (e.g. "ofd2html-0.1.0-py3-none-any.whl"). micropip requires the real name.
const WHEEL_MANIFEST = "./wheel.txt";

const $ = (id) => document.getElementById(id);
const status = (msg) => { $("status").textContent = msg; };
const log = (msg) => {
    const el = $("log");
    el.textContent += "\n" + msg;
    el.scrollTop = el.scrollHeight;
};

let pyodide = null;
let lastHtml = null;
let lastName = "converted";

async function boot() {
    try {
        status("加载 Pyodide…");
        pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX });
        log("[ok] Pyodide " + pyodide.version + " 已加载");

        status("加载 lxml…");
        await pyodide.loadPackage("lxml");
        log("[ok] lxml 已加载");

        status("安装 ofd2html…");
        await pyodide.loadPackage("micropip");
        const wheelName = (await (await fetch(WHEEL_MANIFEST, { cache: "no-cache" })).text()).trim();
        if (!wheelName) throw new Error("wheel.txt is empty");
        const wheelUrl = "./" + wheelName;
        log("[info] wheel = " + wheelName);
        // deps=False: skip fastapi/uvicorn/pydantic (server-side only).
        await pyodide.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(wheelUrl)}, deps=False)
`);
        log("[ok] ofd2html 已安装");

        // Smoke test import.
        pyodide.runPython("import ofd2html");
        log("[ok] import ofd2html 成功，版本 = " +
            pyodide.runPython("ofd2html.__version__"));

        $("file").disabled = false;
        status("就绪：选择一个 .ofd 文件");
    } catch (err) {
        status("初始化失败");
        log("[err] " + err);
        console.error(err);
    }
}

async function convert(file) {
    if (!pyodide) return;
    status("读取文件…");
    setExportButtonsEnabled(false);
    $("preview").srcdoc = "";
    lastHtml = null;
    lastName = file.name.replace(/\.ofd$/i, "") || "converted";
    $("filename").textContent = file.name + "  (" + file.size.toLocaleString() + " bytes)";

    try {
        const buf = new Uint8Array(await file.arrayBuffer());
        pyodide.FS.writeFile("/tmp/input.ofd", buf);
        status("转换中…");
        log("[run] 调用 ofd2html.ofd_to_html(" + buf.length + " bytes)");
        const t0 = performance.now();
        const html = pyodide.runPython(`
import ofd2html
with open("/tmp/input.ofd", "rb") as f:
    _ofd2html_out = ofd2html.ofd_to_html(f.read())
_ofd2html_out
`);
        const ms = (performance.now() - t0).toFixed(0);
        log("[ok] 转换完成，HTML " + html.length.toLocaleString() + " chars，用时 " + ms + " ms");
        lastHtml = html;
        $("preview").srcdoc = html;
        // Wait for the iframe to parse the new srcdoc before enabling the
        // export buttons (they depend on querying SVGs from inside it).
        await new Promise((resolve) => {
            $("preview").addEventListener("load", resolve, { once: true });
        });
        setExportButtonsEnabled(true);
        status("转换完成");
    } catch (err) {
        status("转换失败");
        log("[err] " + err);
        console.error(err);
    }
}

function download() {
    if (!lastHtml) return;
    const blob = new Blob([lastHtml], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = lastName + ".html";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

// --------------------------------------------------------------------------
// Print / PDF / PNG export
//
// The converted HTML wraps each OFD page in a <div> containing exactly one
// <svg width="Wmm" height="Hmm" viewBox="0 0 W H"> element. We collect those
// SVGs from the preview <iframe> and rasterize them client-side.
// --------------------------------------------------------------------------

const MM_PER_INCH = 25.4;
const RENDER_DPI = 200;          // raster DPI for PDF/PNG output

function getPreviewDoc() {
    const iframe = $("preview");
    const doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
    if (!doc || !doc.body) throw new Error("预览尚未就绪");
    return doc;
}

function getPageSvgs() {
    const doc = getPreviewDoc();
    const svgs = Array.from(doc.querySelectorAll("svg"));
    if (svgs.length === 0) throw new Error("未找到页面 SVG");
    return svgs;
}

/** Parse "210mm" → 210 (number, in millimetres). Returns NaN if no unit. */
function parseMm(value) {
    if (!value) return NaN;
    const m = String(value).match(/([-+]?[0-9]*\.?[0-9]+)\s*mm/i);
    return m ? parseFloat(m[1]) : NaN;
}

/** Read a page SVG's physical size in millimetres. */
function svgSizeMm(svg) {
    let w = parseMm(svg.getAttribute("width"));
    let h = parseMm(svg.getAttribute("height"));
    if (!isFinite(w) || !isFinite(h)) {
        const vb = (svg.getAttribute("viewBox") || "").split(/[\s,]+/).map(Number);
        if (vb.length === 4) { w = vb[2]; h = vb[3]; }
    }
    if (!isFinite(w) || !isFinite(h) || w <= 0 || h <= 0) {
        throw new Error("无法解析 SVG 物理尺寸");
    }
    return { w, h };
}

/**
 * Rasterize an SVG element to a PNG data URL at the requested DPI.
 *
 * We serialize the SVG (with explicit pixel width/height to control output
 * resolution), draw it onto a Canvas via an <img>, then export as PNG.
 */
function svgToPngDataUrl(svg, widthMm, heightMm, dpi) {
    const pxW = Math.max(1, Math.round((widthMm / MM_PER_INCH) * dpi));
    const pxH = Math.max(1, Math.round((heightMm / MM_PER_INCH) * dpi));

    // Clone so we can force pixel dimensions without mutating the preview.
    const clone = svg.cloneNode(true);
    if (!clone.getAttribute("xmlns")) clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", pxW);
    clone.setAttribute("height", pxH);

    const xml = new XMLSerializer().serializeToString(clone);
    const blob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);

    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
            try {
                const canvas = document.createElement("canvas");
                canvas.width = pxW;
                canvas.height = pxH;
                const ctx = canvas.getContext("2d");
                ctx.fillStyle = "#fff";
                ctx.fillRect(0, 0, pxW, pxH);
                ctx.drawImage(img, 0, 0, pxW, pxH);
                URL.revokeObjectURL(url);
                resolve({ dataUrl: canvas.toDataURL("image/png"), pxW, pxH });
            } catch (e) {
                URL.revokeObjectURL(url);
                reject(e);
            }
        };
        img.onerror = (e) => {
            URL.revokeObjectURL(url);
            reject(new Error("SVG 光栅化失败：" + (e && e.message ? e.message : e)));
        };
        img.src = url;
    });
}

function saveDataUrl(dataUrl, filename) {
    const a = document.createElement("a");
    a.href = dataUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
}

async function printPreview() {
    try {
        const iframe = $("preview");
        const win = iframe.contentWindow;
        if (!win) throw new Error("预览未就绪");
        // Hide drop-shadows etc. when printing to avoid grey backgrounds.
        const doc = getPreviewDoc();
        if (!doc.getElementById("__ofd2html_print_style")) {
            const st = doc.createElement("style");
            st.id = "__ofd2html_print_style";
            st.textContent =
                "@media print {" +
                "  html, body { background: #fff !important; margin: 0 !important; }" +
                "  body > div { gap: 0 !important; }" +
                "  body * { box-shadow: none !important; }" +
                "  @page { margin: 0; }" +
                "}";
            doc.head.appendChild(st);
        }
        win.focus();
        win.print();
    } catch (err) {
        log("[err] 打印失败：" + err);
    }
}

async function exportPdf() {
    try {
        if (!window.jspdf || !window.jspdf.jsPDF) throw new Error("jsPDF 未加载");
        const { jsPDF } = window.jspdf;
        const svgs = getPageSvgs();
        status("生成 PDF（" + svgs.length + " 页）…");
        let pdf = null;
        for (let i = 0; i < svgs.length; i++) {
            const { w, h } = svgSizeMm(svgs[i]);
            const { dataUrl } = await svgToPngDataUrl(svgs[i], w, h, RENDER_DPI);
            if (!pdf) {
                pdf = new jsPDF({
                    unit: "mm",
                    format: [w, h],
                    orientation: w >= h ? "landscape" : "portrait",
                    compress: true,
                });
            } else {
                pdf.addPage([w, h], w >= h ? "landscape" : "portrait");
            }
            pdf.addImage(dataUrl, "PNG", 0, 0, w, h, undefined, "FAST");
            log("[pdf] 页 " + (i + 1) + "/" + svgs.length + " 完成 (" + w.toFixed(1) + "x" + h.toFixed(1) + " mm)");
        }
        pdf.save(lastName + ".pdf");
        status("PDF 已下载");
    } catch (err) {
        status("PDF 导出失败");
        log("[err] " + err);
    }
}

async function exportPng() {
    try {
        const svgs = getPageSvgs();
        status("生成 PNG（" + svgs.length + " 页）…");
        for (let i = 0; i < svgs.length; i++) {
            const { w, h } = svgSizeMm(svgs[i]);
            const { dataUrl } = await svgToPngDataUrl(svgs[i], w, h, RENDER_DPI);
            const suffix = svgs.length > 1
                ? "-page-" + String(i + 1).padStart(String(svgs.length).length, "0")
                : "";
            saveDataUrl(dataUrl, lastName + suffix + ".png");
            log("[png] 页 " + (i + 1) + "/" + svgs.length + " 已下载");
        }
        status("PNG 已下载");
    } catch (err) {
        status("PNG 导出失败");
        log("[err] " + err);
    }
}

function setExportButtonsEnabled(enabled) {
    for (const id of ["download", "print", "pdf", "png"]) {
        const el = $(id);
        if (el) el.disabled = !enabled;
    }
}

$("file").addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (f) convert(f);
});
$("download").addEventListener("click", download);
$("print").addEventListener("click", printPreview);
$("pdf").addEventListener("click", exportPdf);
$("png").addEventListener("click", exportPng);

boot();

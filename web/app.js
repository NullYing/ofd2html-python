// Pyodide bootstrap + ofd2html runner.
//
// Strategy: load Pyodide from CDN, install lxml from Pyodide's repo,
// then micropip-install the locally built ofd2html wheel with deps=False
// (we don't need fastapi/uvicorn/pydantic in the browser).

const PYODIDE_INDEX = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
const WHEEL_URL = "./ofd2html-latest.whl";

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
        // deps=False: skip fastapi/uvicorn/pydantic (server-side only).
        await pyodide.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(WHEEL_URL)}, deps=False)
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
    $("download").disabled = true;
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
        $("download").disabled = false;
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

$("file").addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (f) convert(f);
});
$("download").addEventListener("click", download);

boot();

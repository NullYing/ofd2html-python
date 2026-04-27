"""End-to-end tests against the FastAPI service using the real sample OFDs."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from lxml import html as lxml_html

from ofd2html.api.app import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["msg"] == "ok"


def test_convert_returns_html(ofd_path: Path, ofd_bytes: bytes) -> None:
    """Replicates the caller pattern from the refactor plan §5:

    resp = requests.post(url, params={"task_id": task_id},
                         files=[("file", ("invoice.ofd", file,
                                          "application/octet-stream"))])
    """
    task_id = f"t-{ofd_path.stem}"
    resp = client.post(
        "/ofd/convert",
        params={"task_id": task_id},
        files=[("file", (ofd_path.name, ofd_bytes, "application/octet-stream"))],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task_id"] == task_id, body
    assert body["code"] == 200, body
    assert body["msg"] == "ok"
    html = body["data"]
    assert isinstance(html, str) and html.startswith("<!DOCTYPE html>")

    # Parse HTML and verify at least one <svg> page made it through.
    root = lxml_html.fromstring(html)
    svgs = root.xpath("//*[local-name()='svg']")
    assert len(svgs) >= 1, f"expected >= 1 <svg>, got {len(svgs)}"


def test_reject_empty_upload() -> None:
    resp = client.post(
        "/ofd/convert",
        params={"task_id": "t-empty"},
        files=[("file", ("empty.ofd", b"", "application/octet-stream"))],
    )
    body = resp.json()
    assert body["code"] == 400
    assert body["data"] is None
    assert body["task_id"] == "t-empty"


def test_reject_garbage() -> None:
    resp = client.post(
        "/ofd/convert",
        params={"task_id": "t-garbage"},
        files=[("file", ("bad.ofd", b"this is not a zip", "application/octet-stream"))],
    )
    body = resp.json()
    assert body["code"] == 400
    assert body["data"] is None

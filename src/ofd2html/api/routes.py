"""FastAPI routes for OFD -> HTML conversion."""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ..html.exporter import ofd_to_html
from .schemas import ConvertResponse

router = APIRouter()


# Configurable limits.
_MAX_BYTES = int(os.environ.get("OFD_MAX_BYTES", str(20 * 1024 * 1024)))
_HARD_TIMEOUT = float(os.environ.get("OFD_CONVERT_TIMEOUT", "4.5"))


def _resp(
    code: int, msg: str, *, data: str | None = None, task_id: str | None = None
) -> JSONResponse:
    """Always reply HTTP 200 -- business status lives in ``code``."""
    body = ConvertResponse(code=code, msg=msg, data=data, task_id=task_id).model_dump()
    return JSONResponse(content=body, status_code=200)


@router.get("/health")
async def health() -> JSONResponse:
    return _resp(200, "ok")


@router.post("/ofd/convert")
async def convert_ofd(
    task_id: str = Query(
        ..., description="Caller-provided task identifier; echoed back."
    ),
    file: UploadFile = File(..., description="OFD file binary."),
) -> JSONResponse:
    try:
        payload = await file.read()
    except Exception as exc:  # network/IO read errors
        return _resp(400, f"failed to read upload: {exc}", task_id=task_id)

    if not payload:
        return _resp(400, "empty upload", task_id=task_id)
    if len(payload) > _MAX_BYTES:
        return _resp(
            400,
            f"file too large: {len(payload)} bytes (limit {_MAX_BYTES})",
            task_id=task_id,
        )

    try:
        # Convert in threadpool so CPU work doesn't block the event loop;
        # apply a hard timeout to honour upstream client SLA (`timeout=5`).
        html = await asyncio.wait_for(
            run_in_threadpool(ofd_to_html, payload),
            timeout=_HARD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return _resp(504, "convert timeout", task_id=task_id)
    except ValueError as exc:
        return _resp(400, str(exc), task_id=task_id)
    except Exception as exc:  # pragma: no cover - last-resort guard
        return _resp(500, f"convert failed: {exc}", task_id=task_id)

    return _resp(200, "ok", data=html, task_id=task_id)

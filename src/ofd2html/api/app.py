"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from .routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="ofd2html",
        version="0.1.0",
        description="OFD -> HTML conversion service.",
    )
    app.include_router(router)
    return app


# Module-level instance for `uvicorn ofd2html.api.app:app`.
app = create_app()

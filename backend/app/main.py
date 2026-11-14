import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin_auth, health, jurisdictions, regulations, review, sources
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title="JSE Local Regulations", version="0.1.0", docs_url="/api/docs",
                  openapi_url="/api/openapi.json")
    app.include_router(health.router, prefix="/api")
    app.include_router(admin_auth.router, prefix="/api")
    app.include_router(jurisdictions.router, prefix="/api")
    app.include_router(sources.router, prefix="/api")
    app.include_router(sources.admin_router, prefix="/api")
    app.include_router(regulations.router, prefix="/api")
    app.include_router(review.router, prefix="/api")

    if settings.static_dir:
        _mount_spa(app, settings.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend, falling back to index.html for client-side routes."""
    index = static_dir / "index.html"
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, headers={"X-Robots-Tag": "noindex"})


app = create_app()

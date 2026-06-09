from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

_HERE = Path(__file__).parent
_DOCS = _HERE.parent / "docs"
if not _DOCS.is_dir():
    _DOCS = _HERE.parents[2] / "docs"


def _page(name: str) -> str:
    return (_HERE / name).read_text()


def create_app() -> FastAPI:
    app = FastAPI(title="Orwell Dashboard", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _page("page.html")

    @app.get("/config", response_class=HTMLResponse)
    def config():
        return _page("config.html")

    @app.get("/docs", response_class=HTMLResponse)
    def docs():
        return _page("docs.html")

    @app.get("/architecture.d2", response_class=PlainTextResponse)
    def architecture_source():
        return (_DOCS / "diagrams" / "architecture.d2").read_text()

    @app.get("/architecture.svg")
    def architecture_diagram():
        return FileResponse(_DOCS / "diagrams" / "architecture.svg", media_type="image/svg+xml")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()

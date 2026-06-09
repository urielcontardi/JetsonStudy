from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

_HERE = Path(__file__).parent
_PACKAGED_DOCS = Path("/app/docs/diagrams")
_DOCS = _PACKAGED_DOCS if _PACKAGED_DOCS.exists() else _HERE.parents[2] / "docs/diagrams"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Orwell Operations Portal",
        description="Dashboard e documentação operacional do Orwell.",
        docs_url=None,
        redoc_url=None,
    )
    html = (_HERE / "page.html").read_text()

    @app.get("/", response_class=HTMLResponse)
    @app.get("/docs", response_class=HTMLResponse)
    def index():
        return html

    @app.get("/architecture.svg", response_class=FileResponse)
    def architecture_svg():
        return FileResponse(_DOCS / "architecture.svg", media_type="image/svg+xml")

    @app.get("/architecture.d2", response_class=PlainTextResponse)
    def architecture_source():
        return (_DOCS / "architecture.d2").read_text()

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()

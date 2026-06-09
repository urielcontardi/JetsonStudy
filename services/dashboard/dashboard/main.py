from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

_HERE = Path(__file__).parent


def create_app() -> FastAPI:
    app = FastAPI(title="Orwell Dashboard", docs_url=None, redoc_url=None)
    html = (_HERE / "page.html").read_text()

    @app.get("/", response_class=HTMLResponse)
    def index():
        return html

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()

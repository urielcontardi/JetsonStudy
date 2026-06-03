from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

_HERE = Path(__file__).parent


def create_app() -> FastAPI:
    app = FastAPI(title="Orwell Dashboard")
    clip_api_url = os.environ.get("CLIP_API_URL", "http://clip-api:8080")
    preview_url = os.environ.get("PREVIEW_URL", "http://localhost:8888")
    html = (_HERE / "page.html").read_text()
    html = html.replace("__CLIP_API_URL__", clip_api_url)
    html = html.replace("__PREVIEW_URL__", preview_url)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return html

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()

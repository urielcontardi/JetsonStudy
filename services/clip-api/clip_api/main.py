from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from orwell_shared.clips import NoSegments, extract_clip
from orwell_shared.index import SegmentIndex

from .settings import data_dir, index_db_path


def _to_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def create_app(extract_fn=extract_clip) -> FastAPI:
    app = FastAPI(title="Orwell Clip API")
    index = SegmentIndex(index_db_path())
    ddir = data_dir()

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/cameras")
    def cameras():
        return index.cameras()

    @app.get("/segments")
    def segments(camera: str, start: str, end: str):
        segs = index.query(camera, _to_epoch(start), _to_epoch(end))
        return [s.path for s in segs]

    @app.get("/clips")
    def clips(camera: str = Query(...), start: str = Query(...), end: str = Query(...)):
        s, e = _to_epoch(start), _to_epoch(end)
        out = Path(tempfile.gettempdir()) / f"clip-{camera}-{int(s)}-{int(e)}.mp4"
        try:
            extract_fn(index, camera, s, e, out)
        except NoSegments:
            raise HTTPException(status_code=404, detail="no segments for window")
        return FileResponse(str(out), media_type="video/mp4", filename=out.name)

    return app


app = create_app()

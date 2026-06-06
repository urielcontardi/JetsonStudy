from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from orwell_shared.clips import NoSegments, extract_clip, extract_event_clip
from orwell_shared.events import EventIndex
from orwell_shared.index import SegmentIndex

from .settings import data_dir, events_dir, index_db_path


def _to_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def create_app(extract_fn=extract_clip, extract_event_fn=extract_event_clip) -> FastAPI:
    app = FastAPI(title="Orwell Clip API")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    index = SegmentIndex(index_db_path())
    event_index = EventIndex(index_db_path())
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

    @app.get("/range")
    def range_endpoint(camera: str = Query(...)):
        from datetime import datetime, timezone
        oldest = index.oldest(camera)
        newest_row = index._conn.execute(
            "SELECT * FROM segments WHERE camera_id=? ORDER BY t_end DESC LIMIT 1",
            (camera,)
        ).fetchone()
        newest = index._row(newest_row) if newest_row else None

        def fmt(ts: float | None) -> str | None:
            if ts is None:
                return None
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "camera": camera,
            "first": fmt(oldest.t_start) if oldest else None,
            "last":  fmt(newest.t_end)   if newest else None,
        }

    @app.get("/clips")
    def clips(camera: str = Query(...), start: str = Query(...), end: str = Query(...)):
        s, e = _to_epoch(start), _to_epoch(end)
        out = Path(tempfile.gettempdir()) / f"clip-{camera}-{int(s)}-{int(e)}.mp4"
        try:
            extract_fn(index, camera, s, e, out)
        except NoSegments:
            raise HTTPException(status_code=404, detail="no segments for window")
        return FileResponse(str(out), media_type="video/mp4", filename=out.name)

    @app.get("/events")
    def events_list(
        camera: str = Query(...),
        start: str = Query(...),
        end: str = Query(...),
    ):
        s, e = _to_epoch(start), _to_epoch(end)
        evts = event_index.query(camera, s, e)
        return [
            {
                "id": ev.id,
                "camera_id": ev.camera_id,
                "t_evento": ev.t_evento,
                "label": ev.label,
                "confidence": ev.confidence,
                "clip_available": ev.clip_path is not None,
            }
            for ev in evts
        ]

    @app.get("/events/{event_id}/clip")
    def event_clip(event_id: str):
        ev = event_index.get(event_id)
        if ev is None or ev.clip_path is None:
            raise HTTPException(status_code=404, detail="event clip not found")
        out = Path(tempfile.gettempdir()) / f"event-{event_id}.mp4"
        try:
            extract_event_fn(Path(ev.clip_path), out)
        except NoSegments:
            raise HTTPException(status_code=404, detail="clip files not found")
        return FileResponse(str(out), media_type="video/mp4", filename=f"event-{event_id}.mp4")

    return app


app = create_app()

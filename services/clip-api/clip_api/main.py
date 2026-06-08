from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from orwell_shared.clips import NoSegments, extract_clip, extract_event_clip
from orwell_shared.events import EventIndex
from orwell_shared.index import SegmentIndex

from .settings import data_dir, events_dir, index_db_path


def _to_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


class ConfigPatch(BaseModel):
    periodic_upload_enabled: bool | None = None
    periodic_upload_interval_s: int | None = Field(None, ge=60, le=86400)


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

    @app.get("/orwell/events/{sensor_id}")
    def orwell_events(sensor_id: str, start: str = Query(...), end: str = Query(...)):
        s, e = _to_epoch(start), _to_epoch(end)
        evts = event_index.query_all(s, e)
        return {
            "events": [
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
        }

    @app.get("/orwell/clip/{sensor_id}/{event_id}")
    def orwell_clip(sensor_id: str, event_id: str):
        ev = event_index.get(event_id)
        if ev is None or ev.clip_path is None:
            raise HTTPException(status_code=404, detail="clip not found")
        out = Path(tempfile.gettempdir()) / f"orwell-{event_id}.mp4"
        try:
            extract_event_fn(Path(ev.clip_path), out)
        except NoSegments:
            raise HTTPException(status_code=404, detail="clip files not found")
        return FileResponse(str(out), media_type="video/mp4", filename=f"clip-{event_id}.mp4")

    from clip_api.settings import config_path as _config_path

    @app.get("/config")
    def get_config():
        from orwell_shared.config import load_config
        cfg = load_config(_config_path())
        return {
            "periodic_upload_enabled": cfg.conveyor.periodic_upload_enabled,
            "periodic_upload_interval_s": cfg.conveyor.periodic_upload_interval_s,
        }

    @app.patch("/config")
    def patch_config(body: ConfigPatch = Body(...)):
        cfg_path = Path(_config_path())
        raw: dict[str, Any] = yaml.safe_load(cfg_path.read_text()) or {}
        conv = raw.setdefault("conveyor", {})
        if body.periodic_upload_enabled is not None:
            conv["periodic_upload_enabled"] = body.periodic_upload_enabled
        if body.periodic_upload_interval_s is not None:
            conv["periodic_upload_interval_s"] = body.periodic_upload_interval_s
        cfg_path.write_text(yaml.dump(raw))
        from orwell_shared.config import load_config
        cfg = load_config(cfg_path)
        return {
            "periodic_upload_enabled": cfg.conveyor.periodic_upload_enabled,
            "periodic_upload_interval_s": cfg.conveyor.periodic_upload_interval_s,
        }

    @app.get("/upload-stats")
    def upload_stats():
        return event_index.upload_stats()

    return app


app = create_app()

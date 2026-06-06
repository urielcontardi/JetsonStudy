from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from orwell_shared.events import Event, EventIndex


def flush_event_buffer(
    tmpfs_dir: str,
    events_dir: str,
    event_id: str,
    camera_id: str,
) -> list[Path]:
    """Copia buf-0.m4s e buf-1.m4s do tmpfs para /events/<event_id>/."""
    buf_dir = Path(tmpfs_dir) / camera_id
    out_dir = Path(events_dir) / event_id
    out_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for i in range(2):
        src = buf_dir / f"buf-{i}.m4s"
        if src.exists():
            dst = out_dir / src.name
            shutil.copy2(src, dst)
            copied.append(dst)
    return copied


def handle_detection(
    camera_id: str,
    t_evento: float,
    label: str,
    confidence: float,
    bbox: dict | None,
    tmpfs_dir: str,
    events_dir: str,
    event_index: EventIndex,
) -> str:
    """Persiste evento no índice e faz flush do event buffer. Retorna o event_id."""
    event_id = str(uuid.uuid4())
    clip_files = flush_event_buffer(tmpfs_dir, events_dir, event_id, camera_id)
    clip_path = str(clip_files[0].parent) if clip_files else None
    event_index.add_event(Event(
        id=event_id,
        camera_id=camera_id,
        t_evento=t_evento,
        label=label,
        confidence=confidence,
        bbox_json=json.dumps(bbox) if bbox is not None else None,
        clip_path=clip_path,
    ))
    return event_id

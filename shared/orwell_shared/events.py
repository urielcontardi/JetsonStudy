from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Event:
    id: str
    camera_id: str
    t_evento: float
    label: str
    confidence: float
    bbox_json: str | None = None
    clip_path: str | None = None
    uploaded_at: float | None = None
    created_at: float = field(default_factory=time.time)
    trigger_type: str = "ai"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    camera_id   TEXT NOT NULL,
    t_evento    REAL NOT NULL,
    label       TEXT NOT NULL,
    confidence  REAL NOT NULL,
    bbox_json   TEXT,
    clip_path   TEXT,
    uploaded_at REAL,
    created_at  REAL NOT NULL,
    trigger_type TEXT NOT NULL DEFAULT 'ai'
);
CREATE INDEX IF NOT EXISTS idx_events_cam_time ON events(camera_id, t_evento);
"""

_MIGRATION_ADD_TRIGGER_TYPE = (
    "ALTER TABLE events ADD COLUMN trigger_type TEXT NOT NULL DEFAULT 'ai'"
)


class EventIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        try:
            self._conn.execute(_MIGRATION_ADD_TRIGGER_TYPE)
            self._conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise

    def add_event(self, event: Event) -> None:
        self._conn.execute(
            "INSERT INTO events"
            "(id,camera_id,t_evento,label,confidence,bbox_json,clip_path,uploaded_at,created_at,trigger_type)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (event.id, event.camera_id, event.t_evento, event.label, event.confidence,
             event.bbox_json, event.clip_path, event.uploaded_at, event.created_at,
             event.trigger_type),
        )
        self._conn.commit()

    def query(self, camera_id: str, start: float, end: float) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE camera_id=? AND t_evento>=? AND t_evento<=?"
            " ORDER BY t_evento",
            (camera_id, start, end),
        ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, event_id: str) -> Event | None:
        row = self._conn.execute(
            "SELECT * FROM events WHERE id=?", (event_id,)
        ).fetchone()
        return self._row(row) if row else None

    def pending_uploads(self) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE uploaded_at IS NULL ORDER BY t_evento"
        ).fetchall()
        return [self._row(r) for r in rows]

    def mark_uploaded(self, event_id: str) -> None:
        import time as _time
        self._conn.execute(
            "UPDATE events SET uploaded_at=? WHERE id=?",
            (_time.time(), event_id),
        )
        self._conn.commit()

    def mark_upload_failed(self, event_id: str) -> None:
        self._conn.execute(
            "UPDATE events SET uploaded_at=? WHERE id=?",
            (-1.0, event_id),
        )
        self._conn.commit()

    def upload_stats(self) -> dict:
        row = self._conn.execute(
            "SELECT "
            "  COUNT(CASE WHEN uploaded_at IS NULL THEN 1 END) AS pending, "
            "  COUNT(CASE WHEN uploaded_at = -1.0 THEN 1 END) AS failed, "
            "  MAX(CASE WHEN uploaded_at > 0 THEN uploaded_at END) AS last_uploaded_at "
            "FROM events"
        ).fetchone()
        return {
            "pending": row["pending"],
            "failed": row["failed"],
            "last_uploaded_at": row["last_uploaded_at"],
        }

    @staticmethod
    def _row(r: sqlite3.Row) -> Event:
        return Event(
            id=r["id"], camera_id=r["camera_id"], t_evento=r["t_evento"],
            label=r["label"], confidence=r["confidence"], bbox_json=r["bbox_json"],
            clip_path=r["clip_path"], uploaded_at=r["uploaded_at"],
            created_at=r["created_at"],
            trigger_type=r["trigger_type"],
        )

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Segment:
    camera_id: str
    t_start: float
    t_end: float
    path: str
    size: int
    created_at: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
    path       TEXT PRIMARY KEY,
    camera_id  TEXT NOT NULL,
    t_start    REAL NOT NULL,
    t_end      REAL NOT NULL,
    size       INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cam_time ON segments(camera_id, t_start);
"""


class SegmentIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add_segment(self, seg: Segment) -> None:
        self._conn.execute(
            "INSERT INTO segments(path,camera_id,t_start,t_end,size,created_at) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "camera_id=excluded.camera_id, t_start=excluded.t_start, "
            "t_end=excluded.t_end, size=excluded.size, created_at=excluded.created_at",
            (seg.path, seg.camera_id, seg.t_start, seg.t_end, seg.size, seg.created_at),
        )
        self._conn.commit()

    def query(self, camera_id: str, start: float, end: float) -> list[Segment]:
        rows = self._conn.execute(
            "SELECT * FROM segments WHERE camera_id=? AND t_end>=? AND t_start<=? "
            "ORDER BY t_start",
            (camera_id, start, end),
        ).fetchall()
        return [self._row(r) for r in rows]

    def oldest(self, camera_id: str | None = None) -> Segment | None:
        if camera_id is None:
            row = self._conn.execute(
                "SELECT * FROM segments ORDER BY t_start LIMIT 1"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM segments WHERE camera_id=? ORDER BY t_start LIMIT 1",
                (camera_id,),
            ).fetchone()
        return self._row(row) if row else None

    def delete(self, path: str) -> None:
        self._conn.execute("DELETE FROM segments WHERE path=?", (path,))
        self._conn.commit()

    def total_size(self) -> int:
        row = self._conn.execute("SELECT COALESCE(SUM(size),0) AS s FROM segments").fetchone()
        return int(row["s"])

    def cameras(self) -> list[str]:
        rows = self._conn.execute("SELECT DISTINCT camera_id FROM segments").fetchall()
        return [r["camera_id"] for r in rows]

    @staticmethod
    def _row(r: sqlite3.Row) -> Segment:
        return Segment(
            camera_id=r["camera_id"], t_start=r["t_start"], t_end=r["t_end"],
            path=r["path"], size=r["size"], created_at=r["created_at"],
        )

import pytest

from orwell_shared.events import Event, EventIndex


@pytest.fixture
def idx(tmp_path):
    return EventIndex(tmp_path / "idx.sqlite")


def _event(**kwargs) -> Event:
    defaults = dict(
        id="evt-1", camera_id="0", t_evento=1000.0,
        label="smoke", confidence=0.85,
    )
    defaults.update(kwargs)
    return Event(**defaults)


def test_add_and_get(idx):
    ev = _event()
    idx.add_event(ev)
    result = idx.get("evt-1")
    assert result is not None
    assert result.label == "smoke"
    assert result.confidence == 0.85


def test_get_missing_returns_none(idx):
    assert idx.get("nope") is None


def test_query_by_camera_and_time(idx):
    idx.add_event(_event(id="e1", camera_id="0", t_evento=1000.0))
    idx.add_event(_event(id="e2", camera_id="0", t_evento=2000.0))
    idx.add_event(_event(id="e3", camera_id="1", t_evento=1000.0))

    result = idx.query("0", 900.0, 1500.0)
    assert len(result) == 1
    assert result[0].id == "e1"


def test_query_returns_ordered_by_time(idx):
    idx.add_event(_event(id="e2", t_evento=2000.0))
    idx.add_event(_event(id="e1", t_evento=1000.0))
    result = idx.query("0", 0.0, 9999.0)
    assert [e.id for e in result] == ["e1", "e2"]


def test_bbox_json_roundtrip(idx):
    ev = _event(bbox_json='{"x":0.1,"y":0.2,"w":0.3,"h":0.4}')
    idx.add_event(ev)
    result = idx.get("evt-1")
    assert result.bbox_json == '{"x":0.1,"y":0.2,"w":0.3,"h":0.4}'


def test_clip_path_and_uploaded_at(idx):
    ev = _event(clip_path="/events/evt-1", uploaded_at=None)
    idx.add_event(ev)
    result = idx.get("evt-1")
    assert result.clip_path == "/events/evt-1"
    assert result.uploaded_at is None


# --- pending_uploads / mark_uploaded / mark_upload_failed ---

import time as _time


def test_pending_uploads_returns_events_with_null_uploaded_at(idx):
    idx.add_event(_event(id="u1", clip_path="/events/u1"))
    pending = idx.pending_uploads()
    assert len(pending) == 1
    assert pending[0].id == "u1"


def test_pending_uploads_excludes_already_uploaded(idx):
    idx.add_event(_event(id="u2", clip_path="/events/u2"))
    idx.mark_uploaded("u2")
    assert idx.pending_uploads() == []


def test_pending_uploads_excludes_permanent_failures(idx):
    idx.add_event(_event(id="u3", clip_path="/events/u3"))
    idx.mark_upload_failed("u3")
    assert idx.pending_uploads() == []


def test_mark_uploaded_sets_timestamp(idx):
    idx.add_event(_event(id="u4", clip_path="/events/u4"))
    before = _time.time()
    idx.mark_uploaded("u4")
    after = _time.time()
    result = idx.get("u4")
    assert result.uploaded_at is not None
    assert before <= result.uploaded_at <= after


def test_pending_uploads_multiple_events(idx):
    for i in ("p1", "p2", "p3"):
        idx.add_event(_event(id=i, clip_path=f"/events/{i}"))
    idx.mark_uploaded("p2")
    ids = {e.id for e in idx.pending_uploads()}
    assert ids == {"p1", "p3"}


def test_trigger_type_default_is_ai(idx):
    ev = _event()
    idx.add_event(ev)
    result = idx.get("evt-1")
    assert result.trigger_type == "ai"


def test_trigger_type_periodic_persists(idx):
    ev = _event(id="p1", trigger_type="periodic")
    idx.add_event(ev)
    result = idx.get("p1")
    assert result.trigger_type == "periodic"


def test_trigger_type_migration_on_existing_db(tmp_path):
    """DB sem coluna trigger_type deve ser migrado automaticamente."""
    import sqlite3
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE events (
            id TEXT PRIMARY KEY, camera_id TEXT NOT NULL, t_evento REAL NOT NULL,
            label TEXT NOT NULL, confidence REAL NOT NULL, bbox_json TEXT,
            clip_path TEXT, uploaded_at REAL, created_at REAL NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO events VALUES('e1','cam0',1.0,'smoke',0.9,NULL,NULL,NULL,1.0)"
    )
    conn.commit()
    conn.close()

    idx = EventIndex(db)
    ev = idx.get("e1")
    assert ev is not None
    assert ev.trigger_type == "ai"

    # Verifica que a DB migrada aceita novos eventos
    idx.add_event(Event(id="e2", camera_id="cam0", t_evento=2.0, label="smoke", confidence=0.9, trigger_type="periodic"))
    assert idx.get("e2").trigger_type == "periodic"


def test_upload_stats_empty(idx):
    stats = idx.upload_stats()
    assert stats["pending"] == 0
    assert stats["failed"] == 0
    assert stats["last_uploaded_at"] is None


def test_upload_stats_counts(idx):
    idx.add_event(_event(id="p1", clip_path="/events/p1"))          # pending
    idx.add_event(_event(id="p2", clip_path="/events/p2"))          # pending
    idx.add_event(_event(id="f1", clip_path="/events/f1"))          # failed
    idx.mark_upload_failed("f1")
    idx.add_event(_event(id="u1", clip_path="/events/u1"))          # uploaded
    idx.mark_uploaded("u1")

    stats = idx.upload_stats()
    assert stats["pending"] == 2
    assert stats["failed"] == 1
    assert stats["last_uploaded_at"] is not None

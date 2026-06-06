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

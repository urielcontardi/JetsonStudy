from orwell_shared.events import DetectionEvent


def test_parse_event_json():
    payload = '{"camera_id":"0","ts_event":1780236005.0,"label":"person","score":0.9}'
    ev = DetectionEvent.model_validate_json(payload)
    assert ev.camera_id == "0"
    assert ev.label == "person"
    assert ev.pre_s == 5.0 and ev.post_s == 5.0


def test_clip_window():
    ev = DetectionEvent(camera_id="0", ts_event=1000.0, label="x", score=0.5,
                        pre_s=3, post_s=7)
    assert ev.clip_window() == (997.0, 1007.0)

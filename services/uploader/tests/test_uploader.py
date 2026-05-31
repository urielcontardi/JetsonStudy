from pathlib import Path

from orwell_shared.index import Segment, SegmentIndex
from uploader.handler import handle_event_payload


class FakeStorage:
    def __init__(self):
        self.calls = []

    def put(self, local_path, key, metadata):
        self.calls.append((local_path, key, metadata))
        return f"s3://b/{key}"


def test_handle_event_extracts_window_and_uploads(tmp_path):
    idx = SegmentIndex(tmp_path / "idx.sqlite")
    init = tmp_path / "0" / "init.mp4"; init.parent.mkdir(parents=True); init.write_bytes(b"i")
    for i, start in enumerate([996.0, 1000.0, 1004.0]):
        f = tmp_path / "0" / f"seg-{i}.m4s"; f.write_bytes(b"s")
        idx.add_segment(Segment("0", start, start + 4, str(f), 10, start))
    storage = FakeStorage()

    def fake_extract(index, camera, start, end, out_path, init_path, runner=None):
        Path(out_path).write_bytes(b"CLIP"); return Path(out_path)

    payload = '{"camera_id":"0","ts_event":1000.0,"label":"person","score":0.9,"pre_s":3,"post_s":3}'
    uri = handle_event_payload(payload, idx, storage, data_dir=str(tmp_path),
                               extract_fn=fake_extract)
    assert uri.startswith("s3://b/")
    assert storage.calls[0][2]["camera"] == "0"   # metadata
    assert storage.calls[0][2]["label"] == "person"

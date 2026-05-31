from orwell_shared.config import CloudConfig
from orwell_shared.storage import get_backend
from orwell_shared.storage.local import LocalStorageBackend
from orwell_shared.storage.s3 import S3StorageBackend


def test_local_backend_copies_and_returns_uri(tmp_path):
    src = tmp_path / "clip.mp4"; src.write_bytes(b"data")
    dest_dir = tmp_path / "uploads"
    backend = LocalStorageBackend(str(dest_dir))
    uri = backend.put(str(src), "events/clip.mp4", {"camera": "0"})
    assert uri == f"file://{dest_dir}/events/clip.mp4"
    assert (dest_dir / "events" / "clip.mp4").read_bytes() == b"data"


def test_s3_backend_calls_client(tmp_path):
    src = tmp_path / "clip.mp4"; src.write_bytes(b"data")
    calls = {}

    class FakeClient:
        def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
            calls.update(Filename=Filename, Bucket=Bucket, Key=Key, ExtraArgs=ExtraArgs)

    backend = S3StorageBackend(bucket="my-bucket", prefix="orwell/", client=FakeClient())
    uri = backend.put(str(src), "events/clip.mp4", {"camera": "0"})
    assert calls["Bucket"] == "my-bucket"
    assert calls["Key"] == "orwell/events/clip.mp4"
    assert uri == "s3://my-bucket/orwell/events/clip.mp4"


def test_get_backend_factory_local():
    cfg = CloudConfig(backend="local", local_dir="/tmp/up")
    assert isinstance(get_backend(cfg), LocalStorageBackend)

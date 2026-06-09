from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_recorder_system_dependencies_are_cached_before_application_code():
    dockerfile = (ROOT / "services/recorder/Dockerfile").read_text()

    apt_layer = dockerfile.index("apt-get -o Acquire::Retries=")
    shared_copy = dockerfile.index("COPY shared/orwell_shared")

    assert "# syntax=docker/dockerfile:1.7" in dockerfile
    assert "ffmpeg -version" in dockerfile
    assert "ffprobe -version" in dockerfile
    assert apt_layer < shared_copy

import shutil
import subprocess

import pytest

FFMPEG = shutil.which("ffmpeg")


@pytest.fixture
def sample_segments(tmp_path):
    """Gera init.mp4 + 3 segmentos fMP4 de 2s (cor sólida) para a câmera '0'."""
    if not FFMPEG:
        pytest.skip("ffmpeg não disponível")
    cam_dir = tmp_path / "0"
    cam_dir.mkdir(parents=True)
    starts = [100.0, 102.0, 104.0]
    paths = []
    for i, _ in enumerate(starts):
        out = cam_dir / f"seg-{i}.m4s"
        subprocess.run(
            [FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2:r=15",
             "-c:v", "libx264", "-g", "15",
             "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
             "-f", "mp4",
             str(out)],
            check=True, capture_output=True,
        )
        paths.append((str(out), starts[i]))
    init = cam_dir / "init.mp4"
    init.write_bytes(b"")  # segmentos são auto-contidos; init vazio é tolerado no concat
    return tmp_path, paths

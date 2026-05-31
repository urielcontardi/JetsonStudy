from orwell_shared.config import CameraConfig, CaptureProfile
from recorder.pipeline import build_source_chain, keyframe_interval, max_size_time_ns


def test_keyframe_interval_is_gop_times_fps():
    assert keyframe_interval(CaptureProfile(fps=15, gop_seconds=1.0)) == 15
    assert keyframe_interval(CaptureProfile(fps=30, gop_seconds=2.0)) == 60
    assert keyframe_interval(CaptureProfile(fps=15, gop_seconds=0.0)) == 1  # mínimo 1


def test_build_source_chain_has_expected_elements_and_params():
    cam = CameraConfig(id="0", argus_sensor_id=2)
    chain = build_source_chain(cam, CaptureProfile(width=1920, height=1080, fps=15,
                                                   gop_seconds=1.0, bitrate_kbps=6000))
    assert "nvarguscamerasrc sensor-id=2" in chain
    assert "width=1920,height=1080" in chain
    assert "framerate=15/1" in chain
    assert "x264enc" in chain
    assert "key-int-max=15" in chain
    assert "bitrate=6000" in chain
    assert chain.strip().endswith("h264parse")


def test_max_size_time_ns():
    assert max_size_time_ns(CaptureProfile(segment_seconds=4.0)) == 4_000_000_000

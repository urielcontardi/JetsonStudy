from orwell_shared.config import CameraConfig, CaptureProfile
from recorder.pipeline import (
    build_source_chain,
    encoder_chain,
    keyframe_interval,
    max_size_time_ns,
    parser_element,
)


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


def test_parser_element_by_codec():
    assert parser_element(CaptureProfile(codec="h264")) == "h264parse"
    assert parser_element(CaptureProfile(codec="h265", encoder="hw")) == "h265parse"


def test_encoder_chain_hw_h265_uses_nvenc_and_bps():
    prof = CaptureProfile(codec="h265", encoder="hw", fps=30, gop_seconds=1.0,
                          bitrate_kbps=8000)
    chain = encoder_chain(prof)
    assert "nvv4l2h265enc" in chain
    assert "bitrate=8000000" in chain      # kbps -> bps
    assert "iframeinterval=30" in chain     # gop_seconds * fps
    assert "nvvidconv" not in chain         # HW fica em NVMM, sem cópia p/ CPU


def test_encoder_chain_hw_h264_uses_nvenc():
    prof = CaptureProfile(codec="h264", encoder="hw", fps=15, gop_seconds=1.0,
                          bitrate_kbps=6000)
    chain = encoder_chain(prof)
    assert "nvv4l2h264enc" in chain
    assert "bitrate=6000000" in chain
    assert "iframeinterval=15" in chain


def test_encoder_chain_sw_h264_uses_x264_and_kbps_and_convert():
    prof = CaptureProfile(codec="h264", encoder="sw", fps=15, gop_seconds=1.0,
                          bitrate_kbps=6000)
    chain = encoder_chain(prof)
    assert "x264enc" in chain
    assert "bitrate=6000" in chain          # x264enc usa kbps
    assert "key-int-max=15" in chain
    assert "nvvidconv" in chain             # baixa NVMM -> CPU (I420)
    assert "I420" in chain

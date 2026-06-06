from orwell_shared.config import AIConfig, CameraConfig, CaptureProfile, PreviewConfig
from recorder.pipeline import (
    ai_scale_chain,
    build_raw_source,
    build_source_chain,
    dvr_encoder_chain,
    encoder_chain,
    event_buffer_encoder_chain,
    inference_stage,
    keyframe_interval,
    max_size_time_ns,
    parser_element,
    preview_branch,
)


def test_keyframe_interval_is_gop_times_fps():
    assert keyframe_interval(CaptureProfile(fps=15, gop_seconds=1.0)) == 15
    assert keyframe_interval(CaptureProfile(fps=30, gop_seconds=2.0)) == 60
    assert keyframe_interval(CaptureProfile(fps=15, gop_seconds=0.0)) == 1  # mínimo 1


def test_build_source_chain_hw_h265():
    cam = CameraConfig(id="0", argus_sensor_id=2)
    chain = build_source_chain(cam, CaptureProfile(width=1920, height=1080, fps=30,
                                                   codec="h265", encoder="hw",
                                                   gop_seconds=1.0, bitrate_kbps=8000))
    assert "nvarguscamerasrc sensor-id=2" in chain
    assert "width=1920,height=1080" in chain
    assert "framerate=30/1" in chain
    assert "nvv4l2h265enc" in chain
    assert "iframeinterval=30" in chain
    assert chain.strip().endswith("h265parse")


def test_build_source_chain_sw_h264_fallback():
    cam = CameraConfig(id="1", argus_sensor_id=0)
    chain = build_source_chain(cam, CaptureProfile(width=1280, height=720, fps=15,
                                                   codec="h264", encoder="sw",
                                                   gop_seconds=1.0, bitrate_kbps=4000))
    assert "x264enc" in chain
    assert "key-int-max=15" in chain
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


def test_inference_stage_disabled_is_empty():
    assert inference_stage(AIConfig(enabled=False), num_cameras=2) == ""


def test_inference_stage_enabled_has_nvinfer_chain():
    chain = inference_stage(AIConfig(enabled=True), num_cameras=2)
    assert "nvstreammux" in chain
    assert "batch-size=2" in chain
    assert "nvinfer" in chain
    assert "nvtracker" in chain


def test_preview_branch_disabled_is_empty():
    assert preview_branch(PreviewConfig(enabled=False), camera_id="0") == ""


def test_preview_branch_enabled_pushes_rtsp():
    branch = preview_branch(
        PreviewConfig(enabled=True, rtsp_base_url="rtsp://preview:8554"), camera_id="0")
    assert "rtspclientsink" in branch


def test_build_raw_source_no_encoder():
    cam = CameraConfig(id="0", argus_sensor_id=1)
    chain = build_raw_source(cam, CaptureProfile(width=1920, height=1080, fps=25))
    assert "nvarguscamerasrc sensor-id=1" in chain
    assert "width=1920,height=1080" in chain
    assert "framerate=25/1" in chain
    assert "nvv4l2h265enc" not in chain
    assert "nvv4l2h264enc" not in chain


def test_dvr_encoder_chain_hw_h265_low_bitrate():
    prof = CaptureProfile(codec="h265", encoder="hw", fps=25, gop_seconds=1.0, bitrate_kbps=500)
    chain = dvr_encoder_chain(prof)
    assert "nvv4l2h265enc" in chain
    assert "bitrate=500000" in chain
    assert "iframeinterval=25" in chain
    assert "h265parse" in chain


def test_dvr_encoder_chain_sw_h264():
    prof = CaptureProfile(codec="h264", encoder="sw", fps=25, gop_seconds=1.0, bitrate_kbps=500)
    chain = dvr_encoder_chain(prof)
    assert "x264enc" in chain
    assert "bitrate=500" in chain
    assert "key-int-max=25" in chain


def test_event_buffer_encoder_chain_uses_high_bitrate():
    prof = CaptureProfile(codec="h265", encoder="hw", fps=25, gop_seconds=1.0, bitrate_kbps=500)
    chain = event_buffer_encoder_chain(prof, buf_bitrate_kbps=8000)
    assert "nvv4l2h265enc" in chain
    assert "bitrate=8000000" in chain
    assert "iframeinterval=25" in chain
    assert "bitrate=500000" not in chain


def test_ai_scale_chain_sets_resolution_and_fps():
    chain = ai_scale_chain(input_width=640, input_height=360, inference_fps=8)
    assert "width=640" in chain
    assert "height=360" in chain
    assert "framerate=8/1" in chain
    assert "nvvideoconvert" in chain

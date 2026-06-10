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
    preview_channel,
    preview_feed_branch,
    preview_pipeline_desc,
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


def test_preview_feed_branch_disabled_is_empty():
    assert preview_feed_branch(
        PreviewConfig(enabled=False), camera_id="0", profile=CaptureProfile()
    ) == ""
    assert preview_pipeline_desc(
        PreviewConfig(enabled=False), camera_id="0", profile=CaptureProfile()
    ) == ""


def test_preview_feed_branch_hw_encodes_at_preview_resolution():
    """Feed branch escala e re-encodar em H.264 com resolução/bitrate do PreviewConfig."""
    feed = preview_feed_branch(
        PreviewConfig(enabled=True, width=1280, height=720, bitrate_kbps=2000),
        camera_id="0",
        profile=CaptureProfile(encoder="hw", codec="h264", width=1920, height=1080),
    )
    assert "shmsink" in feed
    assert f"socket-path={preview_channel('0')}" in feed
    assert "nvvideoconvert" in feed
    assert "width=1280" in feed
    assert "height=720" in feed
    assert "nvv4l2h264enc" in feed
    assert "bitrate=2000000" in feed       # NVENC espera bps
    assert "rtspclientsink" not in feed    # RTSP vive no pipeline separado


def test_preview_feed_branch_hw_works_with_h265_dvr():
    """Preview sempre publica H.264, independente do codec do DVR."""
    feed = preview_feed_branch(
        PreviewConfig(enabled=True, width=1280, height=720, bitrate_kbps=2000),
        camera_id="0",
        profile=CaptureProfile(encoder="hw", codec="h265"),
    )
    assert feed != ""
    assert "nvv4l2h264enc" in feed
    assert "nvv4l2h265enc" not in feed


def test_preview_feed_branch_sw_encodes_at_preview_resolution():
    """SW fallback usa x264enc com resolução e bitrate do PreviewConfig."""
    feed = preview_feed_branch(
        PreviewConfig(enabled=True, width=1280, height=720, bitrate_kbps=2000),
        camera_id="0",
        profile=CaptureProfile(encoder="sw", codec="h264"),
    )
    assert "shmsink" in feed
    assert f"socket-path={preview_channel('0')}" in feed
    assert "x264enc" in feed
    assert "width=1280" in feed
    assert "height=720" in feed
    assert "bitrate=2000" in feed          # x264enc usa kbps


def test_preview_pipeline_desc_hw_is_cfr_and_rtsp():
    desc = preview_pipeline_desc(
        PreviewConfig(enabled=True, rtsp_base_url="rtsp://preview:8554", fps=15),
        camera_id="0",
        profile=CaptureProfile(encoder="hw"),
    )
    assert f"shmsrc socket-path={preview_channel('0')}" in desc
    assert "video/x-h264" in desc
    assert "nvv4l2h264enc" not in desc
    assert "rtspclientsink location=rtsp://preview:8554/cam0" in desc
    assert "protocols=tcp" in desc
    assert "retry-delay" not in desc  # reconexão é rebuild via supervisor, não retry interno


def test_preview_pipeline_desc_sw_encoder():
    desc = preview_pipeline_desc(
        PreviewConfig(enabled=True, rtsp_base_url="rtsp://preview:8554"),
        camera_id="1",
        profile=CaptureProfile(encoder="sw", codec="h264"),
    )
    assert "shmsrc" in desc
    assert "rtspclientsink location=rtsp://preview:8554/cam1" in desc


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
    assert "idrinterval=25" in chain
    assert "insert-sps-pps=true" in chain
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

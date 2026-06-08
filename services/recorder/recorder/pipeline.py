"""Construção da descrição do pipeline GStreamer (parte testável, sem GStreamer).

A cadeia abaixo do sink é construída aqui como string; o `splitmuxsink` (que precisa de um
callback Python para nomear os arquivos por epoch) é criado em `main.py`. Assim, a lógica de
montagem do pipeline e os parâmetros do encoder ficam testáveis sem `gi`/GStreamer instalado.

⚠️ Os nomes/propriedades exatos dos elementos NVIDIA (nvarguscamerasrc, nvvidconv) e do muxer
fragmentado devem ser validados no Jetson (JetPack/DeepStream) — ver docs/decisions/0006.
"""
from __future__ import annotations

from orwell_shared.config import AIConfig, CameraConfig, CaptureProfile, PreviewConfig


def keyframe_interval(profile: CaptureProfile) -> int:
    """Frames por GOP = gop_seconds * fps (keyframe ~1s por padrão)."""
    return max(1, round(profile.gop_seconds * profile.fps))


def parser_element(profile: CaptureProfile) -> str:
    """Parser GStreamer conforme o codec."""
    return "h265parse" if profile.codec == "h265" else "h264parse"


def encoder_chain(profile: CaptureProfile) -> str:
    """Cadeia de encode conforme codec/encoder.

    HW (NVENC, Orin NX): nvv4l2h26Xenc, bitrate em bits/s, GOP via iframeinterval,
    frames seguem em NVMM (sem cópia p/ CPU).
    SW (x264enc, fallback Nano): nvvidconv baixa NVMM->CPU (I420), bitrate em kbit/s,
    GOP via key-int-max.
    """
    kf = keyframe_interval(profile)
    if profile.encoder == "hw":
        elem = "nvv4l2h265enc" if profile.codec == "h265" else "nvv4l2h264enc"
        return f"{elem} bitrate={profile.bitrate_kbps * 1000} iframeinterval={kf}"
    # software (somente h264; h265/sw é rejeitado na validação da config)
    return (
        "nvvidconv ! video/x-raw,format=I420 ! "
        f"x264enc speed-preset=superfast tune=zerolatency "
        f"bitrate={profile.bitrate_kbps} key-int-max={kf}"
    )


def build_source_chain(camera: CameraConfig, profile: CaptureProfile) -> str:
    """Cadeia captura→encode→parser (até o parser). O sink é anexado em main.py.

    Encoder e parser são escolhidos por config (HW NVENC na Orin NX, x264enc SW como
    fallback). Ver encoder_chain()/parser_element().
    """
    return (
        f"nvarguscamerasrc sensor-id={camera.argus_sensor_id} sensor-mode=2 ! "
        f"video/x-raw(memory:NVMM),width={profile.width},height={profile.height},"
        f"framerate={profile.fps}/1 ! "
        f"{encoder_chain(profile)} ! "
        f"{parser_element(profile)}"
    )


def inference_stage(ai: AIConfig, num_cameras: int) -> str:
    """Costura de IA (Fase 2). Desligada (ai.enabled=False) → string vazia.

    Ligada → prefixo de inferência batched para inserir entre as fontes e os encoders.
    A montagem em runtime (probe NvDsObjectMeta → MQTT) fica em main.py; aqui só a
    descrição, validada on-device. Ver docs/superpowers/specs/2026-06-01-orwell-nx-rewrite-design.md.
    """
    if not ai.enabled:
        return ""
    return (
        f"nvstreammux name=mux batch-size={num_cameras} ! "
        "nvinfer config-file-path=$NVINFER_CONFIG ! "
        "nvtracker ! nvstreamdemux name=demux"
    )


def preview_branch(preview: PreviewConfig, camera_id: str, profile: CaptureProfile | None = None) -> str:
    """Branch opcional do tee para o MediaMTX (RTSP).

    O tee emite frames NVMM brutos, portanto esta branch precisa encodar antes de
    entregar ao rtspclientsink. Usa H264 (2 Mbps) para máxima compatibilidade com
    clientes RTSP. protocols=tcp evita problemas de NAT/firewall em containers.
    """
    if not preview.enabled:
        return ""
    url = f"{preview.rtsp_base_url.rstrip('/')}/cam{camera_id}"
    if profile is not None and profile.encoder == "hw":
        kf = max(1, round(profile.gop_seconds * profile.fps))
        encode = (
            f"nvvideoconvert ! "
            f"nvv4l2h264enc bitrate=2000000 iframeinterval={kf} ! h264parse ! "
        )
    elif profile is not None:
        kf = max(1, round(profile.gop_seconds * profile.fps))
        encode = (
            f"nvvideoconvert ! video/x-raw,format=I420 ! "
            f"x264enc speed-preset=ultrafast tune=zerolatency bitrate=2000 key-int-max={kf} ! h264parse ! "
        )
    else:
        encode = ""
    return f"{encode}rtspclientsink location={url} protocols=tcp"


def max_size_time_ns(profile: CaptureProfile) -> int:
    """Duração-alvo do segmento em nanossegundos (para splitmuxsink.max-size-time)."""
    return int(profile.segment_seconds * 1_000_000_000)


def build_raw_source(camera: CameraConfig, profile: CaptureProfile) -> str:
    """Cadeia de captura bruta (pré-tee). Emite frames NVMM sem encode."""
    return (
        f"nvarguscamerasrc sensor-id={camera.argus_sensor_id} sensor-mode=2 ! "
        f"video/x-raw(memory:NVMM),width={profile.width},height={profile.height},"
        f"framerate={profile.fps}/1"
    )


def dvr_encoder_chain(profile: CaptureProfile) -> str:
    """Branch A: nvvideoconvert + encoder + parser para o NVMe (bitrate de arquivo)."""
    kf = keyframe_interval(profile)
    if profile.encoder == "hw":
        elem = "nvv4l2h265enc" if profile.codec == "h265" else "nvv4l2h264enc"
        return (
            f"nvvideoconvert ! "
            f"{elem} bitrate={profile.bitrate_kbps * 1000} iframeinterval={kf} ! "
            f"{parser_element(profile)}"
        )
    return (
        "nvvideoconvert ! video/x-raw,format=I420 ! "
        f"x264enc speed-preset=superfast tune=zerolatency "
        f"bitrate={profile.bitrate_kbps} key-int-max={kf} ! h264parse"
    )


def event_buffer_encoder_chain(profile: CaptureProfile, buf_bitrate_kbps: int) -> str:
    """Branch C: nvvideoconvert + encoder de alta qualidade para o tmpfs."""
    kf = keyframe_interval(profile)
    if profile.encoder == "hw":
        elem = "nvv4l2h265enc" if profile.codec == "h265" else "nvv4l2h264enc"
        return (
            f"nvvideoconvert ! "
            f"{elem} bitrate={buf_bitrate_kbps * 1000} iframeinterval={kf} ! "
            f"{parser_element(profile)}"
        )
    return (
        "nvvideoconvert ! video/x-raw,format=I420 ! "
        f"x264enc speed-preset=superfast tune=zerolatency "
        f"bitrate={buf_bitrate_kbps} key-int-max={kf} ! h264parse"
    )


def ai_scale_chain(input_width: int, input_height: int, inference_fps: int) -> str:
    """Branch B: nvvideoconvert scale + videorate para inferência TensorRT."""
    return (
        f"nvvideoconvert ! "
        f"video/x-raw(memory:NVMM),width={input_width},height={input_height} ! "
        f"videorate ! video/x-raw,framerate={inference_fps}/1"
    )

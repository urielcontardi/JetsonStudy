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
        f"nvarguscamerasrc sensor-id={camera.argus_sensor_id} ! "
        f"video/x-raw(memory:NVMM),width={profile.width},height={profile.height} ! "
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


def preview_branch(preview: PreviewConfig, camera_id: str) -> str:
    """Branch opcional do tee enviando o stream JÁ CODIFICADO para o MediaMTX (RTSP).

    Desligado (preview.enabled=False) → string vazia (tee tem só o consumidor de
    gravação, custo desprezível). Ligado → empurra para rtsp://.../cam<id>.
    """
    if not preview.enabled:
        return ""
    url = f"{preview.rtsp_base_url.rstrip('/')}/cam{camera_id}"
    return f"rtspclientsink location={url}"


def max_size_time_ns(profile: CaptureProfile) -> int:
    """Duração-alvo do segmento em nanossegundos (para splitmuxsink.max-size-time)."""
    return int(profile.segment_seconds * 1_000_000_000)

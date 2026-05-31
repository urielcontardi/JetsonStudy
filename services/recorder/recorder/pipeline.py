"""Construção da descrição do pipeline GStreamer (parte testável, sem GStreamer).

A cadeia abaixo do sink é construída aqui como string; o `splitmuxsink` (que precisa de um
callback Python para nomear os arquivos por epoch) é criado em `main.py`. Assim, a lógica de
montagem do pipeline e os parâmetros do encoder ficam testáveis sem `gi`/GStreamer instalado.

⚠️ Os nomes/propriedades exatos dos elementos NVIDIA (nvarguscamerasrc, nvvidconv) e do muxer
fragmentado devem ser validados no Jetson (JetPack/DeepStream) — ver docs/decisions/0006.
"""
from __future__ import annotations

from orwell_shared.config import CameraConfig, CaptureProfile


def keyframe_interval(profile: CaptureProfile) -> int:
    """Frames por GOP = gop_seconds * fps (keyframe ~1s por padrão)."""
    return max(1, round(profile.gop_seconds * profile.fps))


def build_source_chain(camera: CameraConfig, profile: CaptureProfile) -> str:
    """Cadeia captura→encode (até h264parse). O sink é anexado em main.py.

    Orin Nano não tem NVENC → encode por software (x264enc). nvvidconv copia NVMM→CPU.
    """
    kf = keyframe_interval(profile)
    return (
        f"nvarguscamerasrc sensor-id={camera.argus_sensor_id} ! "
        f"video/x-raw(memory:NVMM),width={profile.width},height={profile.height},"
        f"framerate={profile.fps}/1 ! "
        f"nvvidconv ! video/x-raw,format=I420 ! "
        f"x264enc speed-preset=superfast tune=zerolatency "
        f"bitrate={profile.bitrate_kbps} key-int-max={kf} ! "
        f"h264parse"
    )


def max_size_time_ns(profile: CaptureProfile) -> int:
    """Duração-alvo do segmento em nanossegundos (para splitmuxsink.max-size-time)."""
    return int(profile.segment_seconds * 1_000_000_000)

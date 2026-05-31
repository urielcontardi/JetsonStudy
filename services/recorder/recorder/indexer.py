"""Reflete os segmentos gravados em disco no índice SQLite, gera a playlist HLS e aplica retenção.

O GStreamer escreve os arquivos `seg-<epoch_ms>.m4s`; este indexador (rodado em loop pelo
`main.py`) os reflete no índice e mantém um `live.m3u8` rolante por câmera. Lógica pura/testável,
desacoplada do GStreamer.
"""
from __future__ import annotations

from pathlib import Path

from orwell_shared.config import CaptureProfile, OrwellConfig
from orwell_shared.index import Segment, SegmentIndex
from orwell_shared.paths import parse_segment_epoch_ms, playlist_path
from orwell_shared.retention import disk_usage, run_eviction


def list_segment_files(data_dir: str, camera_id: str) -> list[Path]:
    base = Path(data_dir) / camera_id
    if not base.exists():
        return []
    return sorted(base.rglob("seg-*.m4s"))


def reflect_segments(index: SegmentIndex, data_dir: str, camera_id: str,
                     profile: CaptureProfile, known: set[str],
                     skip_latest: bool = True) -> list[str]:
    """Adiciona ao índice os segmentos novos. Pula o mais recente (pode estar sendo escrito)."""
    files = list_segment_files(data_dir, camera_id)
    candidates = files[:-1] if (skip_latest and files) else files
    added: list[str] = []
    for f in candidates:
        sp = str(f)
        if sp in known:
            continue
        t_start = parse_segment_epoch_ms(f) / 1000.0
        try:
            size = f.stat().st_size
        except FileNotFoundError:
            continue
        index.add_segment(Segment(camera_id, t_start, t_start + profile.segment_seconds,
                                  sp, size, t_start))
        known.add(sp)
        added.append(sp)
    return added


def build_playlist(data_dir: str, camera_id: str, files: list[Path],
                   segment_seconds: float, window: int = 20) -> str:
    """Gera uma media playlist HLS (fMP4) rolante referenciando os últimos `window` segmentos."""
    cam_root = Path(data_dir) / camera_id
    recent = files[-window:]
    media_seq = max(0, len(files) - len(recent))
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{int(round(segment_seconds))}",
        f"#EXT-X-MEDIA-SEQUENCE:{media_seq}",
        '#EXT-X-MAP:URI="init.mp4"',
    ]
    for f in recent:
        rel = f.relative_to(cam_root).as_posix()
        lines.append(f"#EXTINF:{segment_seconds:.3f},")
        lines.append(rel)
    return "\n".join(lines) + "\n"


def write_playlist(data_dir: str, camera_id: str, profile: CaptureProfile) -> Path:
    files = list_segment_files(data_dir, camera_id)
    content = build_playlist(data_dir, camera_id, files, profile.segment_seconds)
    out = playlist_path(data_dir, camera_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content)
    return out


def run_once(index: SegmentIndex, config: OrwellConfig, known: dict[str, set[str]]) -> dict:
    """Uma passada: reflete segmentos novos, escreve playlists e aplica retenção por disco."""
    added: dict[str, list[str]] = {}
    for cam in config.cameras:
        cam_known = known.setdefault(cam.id, set())
        added[cam.id] = reflect_segments(index, config.retention.data_dir, cam.id,
                                         config.capture, cam_known)
        write_playlist(config.retention.data_dir, cam.id, config.capture)

    used, capacity = disk_usage(config.retention.data_dir)
    evicted = run_eviction(index, used, capacity, config.retention.disk_high_watermark_pct)
    # remove os evictados dos conjuntos "known" para permitir regravação futura
    for cam_known in known.values():
        cam_known.difference_update(evicted)
    return {"added": added, "evicted": evicted}

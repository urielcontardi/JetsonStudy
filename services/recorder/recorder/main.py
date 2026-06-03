"""Recorder do Orwell (Fase 1B) — roda NO JETSON (JetPack/DeepStream).

Captura cada câmera via Argus, codifica via encoder configurável (NVENC HW na Orin NX; x264enc SW
como fallback) e grava segmentos fMP4 de ~segment_seconds via `splitmuxsink`, nomeados por epoch.
Um `tee` após o parser permite um branch de preview opcional (MediaMTX). Um indexador roda em
paralelo, refletindo os segmentos no índice SQLite, gerando a playlist HLS e aplicando retenção.

⚠️ Requer GStreamer + plugins NVIDIA (gi/Gst) — só executa no Jetson. As partes puras
(pipeline.py, indexer.py) têm testes; este arquivo é o "fio" de runtime, validado on-device.
Os imports de `gi` são tardios para o pacote ser importável em máquinas sem GStreamer.
"""
from __future__ import annotations

import os
import threading
import time

from orwell_shared.config import load_config
from orwell_shared.index import SegmentIndex
from orwell_shared.paths import segment_path

from .indexer import run_once
from .pipeline import build_source_chain, max_size_time_ns, preview_branch

INDEXER_PERIOD_S = 2.0


def _make_format_location_cb(data_dir: str, camera_id: str):
    """Callback do splitmuxsink: nomeia cada novo fragmento como seg-<epoch_ms>.m4s."""
    def _cb(_splitmux, _fragment_id, *_args):
        epoch_ms = int(time.time() * 1000)
        path = segment_path(data_dir, camera_id, epoch_ms)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)
    return _cb


def _build_camera_bin(Gst, camera, profile, preview, data_dir: str):
    """Pipeline de uma câmera: captura/encode → tee → splitmuxsink (+ preview opcional)."""
    record_sink = (
        "splitmuxsink name=sink "
        f"max-size-time={max_size_time_ns(profile)} "
        'muxer-factory=mp4mux '
        'muxer-properties="properties,fragment-duration=1000,faststart=true"'
    )
    preview_chain = preview_branch(preview, camera.id)
    desc = build_source_chain(camera, profile) + " ! tee name=t "
    desc += f"t. ! queue ! {record_sink} "
    if preview_chain:
        desc += f"t. ! queue ! {preview_chain} "
    pipeline = Gst.parse_launch(desc)
    sink = pipeline.get_by_name("sink")
    sink.connect("format-location-full", _make_format_location_cb(data_dir, camera.id))
    return pipeline


def _indexer_loop(index: SegmentIndex, config, stop: threading.Event) -> None:
    known: dict[str, set[str]] = {}
    while not stop.is_set():
        try:
            run_once(index, config, known)
        except Exception as exc:  # noqa: BLE001 - loop não pode morrer
            print(f"indexer error: {exc}", flush=True)
        stop.wait(INDEXER_PERIOD_S)


def _available_sensor_ids() -> set[int]:
    """Retorna os sensor-ids disponíveis lendo /dev/video* no host (via /proc ou sysfs).

    O Argus enumera as câmeras como /dev/video0, /dev/video1, etc. O número de
    dispositivos video4linux disponíveis é o número de sensores presentes.
    Não abre o sensor — evita conflito com a CaptureSession do Argus.
    """
    import glob
    devices = glob.glob("/dev/video*")
    return set(range(len(devices)))


def main() -> None:
    import gi  # import tardio (só existe no Jetson)

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst

    Gst.init(None)

    config = load_config(os.environ.get("ORWELL_CONFIG", "/app/config/orwell.yaml"))
    index = SegmentIndex(os.environ.get(
        "ORWELL_INDEX_DB", f"{config.retention.data_dir}/index.sqlite"))

    sensor_ids = _available_sensor_ids()
    available = [cam for cam in config.cameras if cam.argus_sensor_id in sensor_ids]
    skipped = [cam for cam in config.cameras if cam not in available]
    for cam in skipped:
        print(f"recorder: sensor-id={cam.argus_sensor_id} não disponível, ignorando", flush=True)

    if not available:
        print("recorder: nenhuma câmera disponível, saindo", flush=True)
        return

    pipelines = [_build_camera_bin(Gst, cam, config.capture, config.preview,
                                   config.retention.data_dir)
                 for cam in available]
    for p in pipelines:
        p.set_state(Gst.State.PLAYING)
    print(f"recorder: {len(pipelines)} câmera(s) gravando em {config.retention.data_dir}",
          flush=True)

    stop = threading.Event()
    threading.Thread(target=_indexer_loop, args=(index, config, stop), daemon=True).start()

    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for p in pipelines:
            p.set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()

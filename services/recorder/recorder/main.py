"""Recorder do Orwell (Fase 1B) — roda NO JETSON (JetPack/DeepStream).

Captura cada câmera via Argus, codifica em H.264 por software (Orin Nano não tem NVENC) e grava
segmentos fMP4 de ~segment_seconds via `splitmuxsink`, nomeados por epoch. Um indexador roda em
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
from .pipeline import build_source_chain, max_size_time_ns

INDEXER_PERIOD_S = 2.0


def _make_format_location_cb(data_dir: str, camera_id: str):
    """Callback do splitmuxsink: nomeia cada novo fragmento como seg-<epoch_ms>.m4s."""
    def _cb(_splitmux, _fragment_id, *_args):
        epoch_ms = int(time.time() * 1000)
        path = segment_path(data_dir, camera_id, epoch_ms)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)
    return _cb


def _build_camera_bin(Gst, camera, profile, data_dir: str):
    """Monta o pipeline de uma câmera: cadeia de captura/encode + splitmuxsink fragmentado."""
    desc = (
        build_source_chain(camera, profile)
        + " ! splitmuxsink name=sink "
        + f"max-size-time={max_size_time_ns(profile)} "
        + 'muxer-factory=mp4mux '
        + 'muxer-properties="properties,fragment-duration=1000,faststart=true"'
    )
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


def main() -> None:
    import gi  # import tardio (só existe no Jetson)

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst

    Gst.init(None)

    config = load_config(os.environ.get("ORWELL_CONFIG", "/app/config/orwell.yaml"))
    index = SegmentIndex(os.environ.get(
        "ORWELL_INDEX_DB", f"{config.retention.data_dir}/index.sqlite"))

    pipelines = [_build_camera_bin(Gst, cam, config.capture, config.retention.data_dir)
                 for cam in config.cameras]
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

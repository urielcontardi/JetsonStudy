"""Recorder do Orwell — roda NO JETSON (JetPack/DeepStream).

Pipeline de 3 branches por câmera:
  A — DVR: encode baixo bitrate → NVMe (longa retenção)
  B — IA: scale 640×360 → TensorRT (só se ai.enabled)
  C — Event buffer: encode alto bitrate → tmpfs circular (só se event_buffer.enabled)

Quando nvinfer (branch B) detecta um evento com confiança >= threshold:
  - flush do buffer C → /events/<id>/
  - persiste no EventIndex (SQLite)

⚠️ Requer GStreamer + plugins NVIDIA (gi/Gst) — só executa no Jetson.
Os imports de `gi` e `pyds` são tardios para o pacote ser importável em máquinas sem GStreamer.
"""
from __future__ import annotations

import math
import os
import signal
import threading
import time
from pathlib import Path

from orwell_shared.config import load_config
from orwell_shared.config_watcher import ConfigWatcher
from orwell_shared.events import EventIndex
from orwell_shared.index import SegmentIndex
from orwell_shared.paths import segment_path

from .event_handler import handle_detection
from .indexer import run_once
from .periodic_flusher import PeriodicFlusher
from .preview_pipeline import PreviewPipeline
from .pipeline import (
    ai_scale_chain,
    build_raw_source,
    dvr_encoder_chain,
    event_buffer_encoder_chain,
    max_size_time_ns,
    preview_feed_branch,
    preview_pipeline_desc,
)


def _purge_stale_buffer(tmpfs_dir: str, camera_ids: list[str]) -> None:
    """Remove fragmentos órfãos do event buffer (tmpfs) deixados por sessões anteriores.

    O `max-files` do splitmuxsink só poda os fragmentos da sessão ATUAL; a cada
    restart do recorder (ex.: bus error do rtspclientsink) a sessão anterior fica
    órfã no tmpfs e nunca é removida. Com restarts frequentes o /dev/shm enche
    (visto em 2026-06-09: ~2000 fragmentos / 5 GB). No boot a nova sessão começa
    do zero, então é seguro limpar tudo aqui.
    """
    removed = 0
    for camera_id in camera_ids:
        buf_dir = Path(tmpfs_dir) / camera_id
        for frag in buf_dir.glob("buf-*"):
            try:
                frag.unlink()
                removed += 1
            except FileNotFoundError:
                pass
    if removed:
        print(f"recorder: limpeza de boot removeu {removed} fragmento(s) órfão(s) do tmpfs",
              flush=True)

INDEXER_PERIOD_S = 2.0


def _make_format_location_cb(data_dir: str, camera_id: str):
    """Callback do splitmuxsink DVR: nomeia cada fragmento como seg-<epoch_ms>.m4s."""
    def _cb(_splitmux, _fragment_id, *_args):
        epoch_ms = int(time.time() * 1000)
        path = segment_path(data_dir, camera_id, epoch_ms)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)
    return _cb


def _make_buf_format_location_cb(tmpfs_dir: str, camera_id: str):
    """Give every fragment a unique path so completed files are immutable."""
    buf_dir = Path(tmpfs_dir) / camera_id
    buf_dir.mkdir(parents=True, exist_ok=True)

    def _cb(_splitmux, fragment_id, *_args):
        epoch_ms = int(time.time() * 1000)
        return str(buf_dir / f"buf-{int(fragment_id):08d}-{epoch_ms}.mp4")
    return _cb


def _build_camera_bin(Gst, camera, profile, ai_cfg, event_buf_cfg, preview_cfg, data_dir: str):
    """Pipeline de 3 branches para uma câmera."""
    dvr_sink_desc = (
        "splitmuxsink name=dvr_sink "
        f"max-size-time={max_size_time_ns(profile)} "
        "send-keyframe-requests=true "
    )

    desc = build_raw_source(camera, profile) + " ! tee name=t "
    desc += f"t. ! queue ! {dvr_encoder_chain(profile)} ! tee name=encoded "
    desc += f"encoded. ! queue ! {dvr_sink_desc} "

    # O buffer de alta qualidade só é necessário para eventos de IA. Upload periódico usa
    # segmentos do DVR, evitando um segundo splitmuxsink e clipes enormes.
    if event_buf_cfg.enabled and ai_cfg.enabled:
        buffer_segment_s = max(1.0, profile.segment_seconds)
        buf_seg_ns = int(buffer_segment_s * 1_000_000_000)
        max_buffer_files = max(2, math.ceil(event_buf_cfg.buffer_seconds / buffer_segment_s) + 1)
        buf_sink_desc = (
            "splitmuxsink name=buf_sink "
            f"max-size-time={buf_seg_ns} "
            f"max-files={max_buffer_files} "
            "send-keyframe-requests=true "
        )
        desc += (
            f"t. ! queue ! "
            f"{event_buffer_encoder_chain(profile, event_buf_cfg.bitrate_kbps)} ! "
            f"{buf_sink_desc} "
        )

    if ai_cfg.enabled:
        desc += (
            f"t. ! queue ! "
            f"{ai_scale_chain(ai_cfg.input_width, ai_cfg.input_height, ai_cfg.inference_fps)} ! "
            f"nvinfer config-file-path={ai_cfg.model_path} name=ai_infer "
        )

    # Preview: o pipeline de captura só ALIMENTA a ponte intervideo (sink que descarta se
    # ninguém consome). O encode + rtspclientsink vivem num pipeline separado e supervisionado
    # (ver PreviewPipeline em main()), então uma queda de RTSP nunca derruba esta gravação.
    feed_chain = preview_feed_branch(preview_cfg, camera.id, profile)
    if feed_chain:
        desc += f"encoded. ! queue ! {feed_chain} "

    pipeline = Gst.parse_launch(desc)

    dvr = pipeline.get_by_name("dvr_sink")
    dvr.connect("format-location-full", _make_format_location_cb(data_dir, camera.id))

    if event_buf_cfg.enabled and ai_cfg.enabled:
        buf = pipeline.get_by_name("buf_sink")
        buf.connect("format-location-full",
                    _make_buf_format_location_cb(event_buf_cfg.tmpfs_dir, camera.id))

    return pipeline


def _wire_ai_probe(Gst, pipeline, camera, config, event_index: EventIndex) -> None:
    """Conecta probe pyds no nvinfer para disparar handle_detection em cada detecção."""
    ai_infer = pipeline.get_by_name("ai_infer")
    if not ai_infer:
        return
    try:
        import pyds
    except ImportError:
        print("recorder: pyds não disponível — probe de IA desativado", flush=True)
        return

    sink_pad = ai_infer.get_static_pad("sink")

    def _make_probe(cam_id: str):
        def _probe(_pad, info):
            buf = info.get_buffer()
            batch = pyds.gst_buffer_get_nvds_batch_meta(buf.__hash__())
            l_frame = batch.frame_meta_list
            while l_frame:
                frame = pyds.NvDsFrameMeta.cast(l_frame.data)
                l_obj = frame.obj_meta_list
                while l_obj:
                    obj = pyds.NvDsObjectMeta.cast(l_obj.data)
                    if obj.confidence >= config.ai.confidence_threshold:
                        handle_detection(
                            camera_id=cam_id,
                            t_evento=time.time(),
                            label=obj.obj_label,
                            confidence=float(obj.confidence),
                            bbox={
                                "x": obj.rect_params.left / config.capture.width,
                                "y": obj.rect_params.top / config.capture.height,
                                "w": obj.rect_params.width / config.capture.width,
                                "h": obj.rect_params.height / config.capture.height,
                            },
                            tmpfs_dir=config.event_buffer.tmpfs_dir,
                            events_dir=config.retention.events_dir,
                            event_index=event_index,
                        )
                    try:
                        l_obj = l_obj.next
                    except StopIteration:
                        break
                try:
                    l_frame = l_frame.next
                except StopIteration:
                    break
            return Gst.PadProbeReturn.OK
        return _probe

    sink_pad.add_probe(Gst.PadProbeType.BUFFER, _make_probe(camera.id))


def _indexer_loop(index: SegmentIndex, config, stop: threading.Event) -> None:
    known: dict[str, set[str]] = {}
    while not stop.is_set():
        try:
            run_once(index, config, known)
        except Exception as exc:  # noqa: BLE001
            print(f"indexer error: {exc}", flush=True)
        stop.wait(INDEXER_PERIOD_S)


def _available_sensor_ids() -> set[int]:
    import glob
    devices = glob.glob("/dev/video*")
    return set(range(len(devices)))


def main() -> None:
    import gi  # import tardio (só existe no Jetson)

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst

    Gst.init(None)

    config_path = os.environ.get("ORWELL_CONFIG", "/app/config/orwell.yaml")
    config = load_config(config_path)
    db_path = os.environ.get("ORWELL_INDEX_DB", f"{config.retention.data_dir}/index.sqlite")
    index = SegmentIndex(db_path)
    event_index = EventIndex(db_path)

    sensor_ids = _available_sensor_ids()
    available = [cam for cam in config.cameras if cam.argus_sensor_id in sensor_ids]
    skipped = [cam for cam in config.cameras if cam not in available]
    for cam in skipped:
        print(f"recorder: sensor-id={cam.argus_sensor_id} não disponível, ignorando", flush=True)

    if not available:
        print("recorder: nenhuma câmera disponível, saindo", flush=True)
        return

    for cam in available:
        try:
            Path(f"/dev/shm/orwell-preview-cam{cam.id}.sock").unlink()
        except FileNotFoundError:
            pass

    if config.event_buffer.enabled:
        _purge_stale_buffer(config.event_buffer.tmpfs_dir, [cam.id for cam in available])

    pipelines = [
        _build_camera_bin(
            Gst, cam, config.capture,
            config.ai, config.event_buffer, config.preview,
            config.retention.data_dir,
        )
        for cam in available
    ]

    if config.ai.enabled:
        for cam, pipeline in zip(available, pipelines):
            _wire_ai_probe(Gst, pipeline, cam, config, event_index)

    for p in pipelines:
        p.set_state(Gst.State.PLAYING)
    print(f"recorder: {len(pipelines)} câmera(s) gravando em {config.retention.data_dir}",
          flush=True)

    camera_ids = [cam.id for cam in available]
    flusher = PeriodicFlusher(
        cameras=camera_ids,
        tmpfs_dir=config.event_buffer.tmpfs_dir,
        events_dir=config.retention.events_dir,
        event_index=event_index,
        interval_s=config.conveyor.periodic_upload_interval_s,
        enabled=config.conveyor.periodic_upload_enabled and config.conveyor.enabled,
        segment_index=index,
    )
    flusher.start()
    print(
        f"recorder: PeriodicFlusher iniciado "
        f"(enabled={config.conveyor.periodic_upload_enabled}, "
        f"interval={config.conveyor.periodic_upload_interval_s}s)",
        flush=True,
    )

    def _on_config_change(new_cfg) -> None:
        flusher.update_config(
            enabled=new_cfg.conveyor.periodic_upload_enabled and new_cfg.conveyor.enabled,
            interval_s=new_cfg.conveyor.periodic_upload_interval_s,
        )
        print(
            f"recorder: config recarregada — periodic interval={new_cfg.conveyor.periodic_upload_interval_s}s",
            flush=True,
        )

    watcher = ConfigWatcher(config_path, _on_config_change)
    watcher.start()

    stop = threading.Event()
    threading.Thread(target=_indexer_loop, args=(index, config, stop), daemon=True).start()

    loop = GLib.MainLoop()
    def _stop_main_loop(_signum, _frame):
        GLib.idle_add(loop.quit)

    signal.signal(signal.SIGTERM, _stop_main_loop)
    signal.signal(signal.SIGINT, _stop_main_loop)

    def _on_bus_message(bus, msg, _data):
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print(f"recorder: pipeline ERROR — {err} ({dbg}); reiniciando", flush=True)
            GLib.idle_add(loop.quit)
        return True

    for p in pipelines:
        bus = p.get_bus()
        bus.add_signal_watch()
        bus.connect("message", _on_bus_message, None)

    # Pipelines de preview: isolados da gravação. Um erro aqui (ex.: RTSP caiu) é tratado
    # pelo próprio supervisor (rebuild com backoff) e NUNCA chega no loop principal acima.
    preview_pipes: list[PreviewPipeline] = []
    if config.preview.enabled:
        for cam in available:
            desc = preview_pipeline_desc(config.preview, cam.id, config.capture)
            pp = PreviewPipeline(Gst, GLib, desc, name=f"cam{cam.id}")
            pp.start()
            preview_pipes.append(pp)
        print(f"recorder: {len(preview_pipes)} pipeline(s) de preview iniciado(s)", flush=True)

    try:
        loop.run()
    finally:
        stop.set()
        flusher.stop()
        watcher.stop()
        for pp in preview_pipes:
            pp.stop()
        for p in pipelines:
            p.set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()

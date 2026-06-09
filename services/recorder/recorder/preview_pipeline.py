"""Supervisor do pipeline de PREVIEW — isolado da gravação.

O preview vive num pipeline GStreamer próprio (ver pipeline.preview_pipeline_desc), alimentado
pela ponte intervideo a partir do pipeline de captura. Aqui só supervisionamos esse pipeline:
em ERROR/EOS (ex.: queda da conexão RTSP com o MediaMTX), reconstruímos o pipeline com backoff.
Isso NUNCA toca o loop principal nem a gravação no NVMe — apenas o stream de preview pisca
durante a reconexão.

A lógica de backoff (`next_backoff`) é pura e testável sem GStreamer. A classe `PreviewPipeline`
recebe `Gst`/`GLib` por injeção (imports tardios, só existem no Jetson).
"""
from __future__ import annotations

DEFAULT_BACKOFF = (2, 4, 8, 16, 30)
STABLE_AFTER_S = 30  # tempo em PLAYING sem erro para considerar o stream estável e zerar o backoff


def next_backoff(attempt: int, schedule: tuple[int, ...] = DEFAULT_BACKOFF) -> int:
    """Segundos de espera antes da tentativa `attempt` (0-based). Satura no último valor."""
    if not schedule:
        return 0
    if attempt < 0:
        attempt = 0
    return schedule[min(attempt, len(schedule) - 1)]


class PreviewPipeline:
    def __init__(self, Gst, GLib, desc: str, name: str,
                 backoff: tuple[int, ...] = DEFAULT_BACKOFF) -> None:
        self._Gst = Gst
        self._GLib = GLib
        self._desc = desc
        self._name = name
        self._backoff = backoff
        self._attempt = 0
        self._pipeline = None
        self._restart_source = None
        self._stable_source = None
        self._stopped = False

    def start(self) -> None:
        self._build_and_play()

    def _build_and_play(self) -> None:
        if self._stopped:
            return
        Gst = self._Gst
        self._pipeline = Gst.parse_launch(self._desc)
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        self._pipeline.set_state(Gst.State.PLAYING)
        print(f"recorder: preview '{self._name}' PLAYING", flush=True)
        # Se ficar estável por um tempo, zera o backoff (uma queda isolada não deve escalar o delay).
        self._stable_source = self._GLib.timeout_add_seconds(STABLE_AFTER_S, self._mark_stable)

    def _mark_stable(self) -> bool:
        self._stable_source = None
        self._attempt = 0
        return False  # one-shot

    def _teardown(self) -> None:
        if self._stable_source is not None:
            self._GLib.source_remove(self._stable_source)
            self._stable_source = None
        if self._pipeline is not None:
            self._pipeline.set_state(self._Gst.State.NULL)
            self._pipeline = None

    def _on_bus_message(self, _bus, msg) -> bool:
        Gst = self._Gst
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print(f"recorder: preview '{self._name}' ERROR — {err} ({dbg})", flush=True)
            self._schedule_restart()
        elif msg.type == Gst.MessageType.EOS:
            print(f"recorder: preview '{self._name}' EOS", flush=True)
            self._schedule_restart()
        return True

    def _schedule_restart(self) -> None:
        if self._stopped or self._restart_source is not None:
            return
        self._teardown()
        delay = next_backoff(self._attempt, self._backoff)
        self._attempt += 1
        print(f"recorder: preview '{self._name}' reiniciando em {delay}s "
              f"(tentativa {self._attempt})", flush=True)
        self._restart_source = self._GLib.timeout_add_seconds(delay, self._do_restart)

    def _do_restart(self) -> bool:
        self._restart_source = None
        if not self._stopped:
            self._build_and_play()
        return False  # one-shot

    def stop(self) -> None:
        self._stopped = True
        if self._restart_source is not None:
            self._GLib.source_remove(self._restart_source)
            self._restart_source = None
        self._teardown()

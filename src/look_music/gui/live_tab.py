"""Live tab: notes rising from the keys in real time, plus recording a take."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from look_music.gui.preview_widget import PreviewWidget
from look_music.live.audio_capture import AudioRecorder
from look_music.live.clock import SessionClock
from look_music.live.events import NOTE_ON
from look_music.live.level_meter import LevelMeter
from look_music.live.midi_input import MidiInput
from look_music.live.recorder import save_midi
from look_music.live.state import LiveState
from look_music.midi import Song
from look_music.preset import Preset
from look_music.preview.frames import FrameSource

WIDTH, HEIGHT = 1280, 720
NO_AUDIO = "No audio"
NO_PORTS_MSG = "No MIDI ports found — connect the piano by USB and press Refresh"
_METER_RED = "QProgressBar::chunk { background-color: #d33; }"


def _default_midi_ports() -> list[str]:
    from look_music.live.midi_input import list_input_ports

    return list_input_ports()


def _default_audio_inputs() -> list[tuple[int, str]]:
    from look_music.live.audio_capture import list_input_devices

    return list_input_devices()


class PeakHold:
    """Meter smoothing: instant attack, linear decay, and a clip flag held for a while."""

    DECAY_PER_SEC = 20.0  # meter points per second
    CLIP_LEVEL = 0.99
    CLIP_HOLD = 1.0  # seconds

    def __init__(self) -> None:
        self.value = 0.0
        self._clip_until = 0.0
        self._last: float | None = None

    def update(self, level: float, now: float) -> tuple[int, bool]:
        """Return (0..100 display value, clipping) for the raw `level` at time `now`."""
        dt = 0.0 if self._last is None else max(0.0, now - self._last)
        self._last = now
        self.value = min(100.0, max(level * 100.0, self.value - self.DECAY_PER_SEC * dt))
        if level >= self.CLIP_LEVEL:
            self._clip_until = now + self.CLIP_HOLD
        return int(round(self.value)), now < self._clip_until

    def reset(self) -> None:
        self.value = 0.0
        self._clip_until = 0.0
        self._last = None


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


class LiveTab(QWidget):
    """Live view of a connected MIDI keyboard, with optional audio recording of a take."""

    take_saved = Signal(object, object)  # (midi_path: Path, wav_path: Path | None)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        preset: Preset | None = None,
        midi_backend_factory: Callable[[], Any] | None = None,
        audio_stream_factory: Callable[..., Any] | None = None,
        list_midi_ports: Callable[[], list[str]] | None = None,
        list_audio_inputs: Callable[[], list[tuple[int, str]]] | None = None,
        save_dir: Path | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._preset = preset or Preset()
        self._midi_backend_factory = midi_backend_factory
        self._audio_stream_factory = audio_stream_factory
        self._list_midi_ports = list_midi_ports or _default_midi_ports
        self._list_audio_inputs = list_audio_inputs or _default_audio_inputs
        self._save_dir = Path(save_dir) if save_dir else Path.home() / "Music" / "look-music"

        self._frames: FrameSource | None = None
        self._clock: SessionClock | None = None
        self._midi_in: MidiInput | None = None
        self._state: LiveState | None = None
        self._recorder: AudioRecorder | None = None
        self._midi_path: Path | None = None
        self._wav_path: Path | None = None
        self._live = False
        self._recording = False
        self._error = ""
        self._time_fn = time_fn
        self._level_meter: LevelMeter | None = None
        self._hold = PeakHold()
        self._meter_error = ""
        self._saved_note = ""  # suffix shown in the live status after a take is saved

        self.port_combo = QComboBox()
        self.refresh_button = QPushButton("Refresh")
        self.audio_combo = QComboBox()
        self.live_button = QPushButton("Start live")
        self.record_button = QPushButton("Record")
        self.record_button.setEnabled(False)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setMaximumWidth(120)
        self.status_label = QLabel()
        self.preview = PreviewWidget()

        top = QHBoxLayout()
        top.addWidget(QLabel("MIDI:"))
        top.addWidget(self.port_combo, 1)
        top.addWidget(self.refresh_button)
        top.addWidget(QLabel("Audio:"))
        top.addWidget(self.audio_combo, 1)
        top.addWidget(self.live_button)
        top.addWidget(self.record_button)
        top.addWidget(self.meter)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.status_label)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.tick)

        self.refresh_button.clicked.connect(self.refresh_devices)
        self.live_button.clicked.connect(self._toggle_live)
        self.record_button.clicked.connect(self._toggle_record)
        self.audio_combo.currentIndexChanged.connect(self._on_audio_changed)

        self.refresh_devices()

    # -- devices ---------------------------------------------------------------------------

    def refresh_devices(self) -> None:
        """Re-query MIDI ports and audio inputs."""
        self.port_combo.clear()
        try:
            ports = self._list_midi_ports()
        except Exception as exc:
            ports = []
            self._set_status(f"Could not list MIDI ports: {exc}")
        self.port_combo.addItems(ports)

        self.audio_combo.clear()
        self.audio_combo.addItem(NO_AUDIO, None)
        try:
            inputs = self._list_audio_inputs()
        except Exception:
            inputs = []
        for index, name in inputs:
            self.audio_combo.addItem(name, index)
        for i in range(1, self.audio_combo.count()):
            if "microphone" in self.audio_combo.itemText(i).lower():
                self.audio_combo.setCurrentIndex(i)
                break
        self._on_audio_changed()
        if not ports and not self._live:
            self._set_status(NO_PORTS_MSG)

    def _update_meter_visibility(self) -> None:
        self.meter.setVisible(self.audio_combo.currentData() is not None and not self._meter_error)

    def _on_audio_changed(self) -> None:
        self._meter_error = ""
        self._update_meter_visibility()
        if self._live and not self._recording:
            self._start_level_meter()

    def _start_level_meter(self) -> None:
        """(Re)start the input monitor on the selected device so levels show before recording."""
        self._stop_level_meter()
        self._meter_error = ""
        device = self.audio_combo.currentData()
        if device is not None:
            meter = LevelMeter(device, stream_factory=self._audio_stream_factory)
            try:
                meter.start()
                self._level_meter = meter
            except Exception as exc:
                self._meter_error = f"Audio level unavailable: {exc}"
        self._update_meter_visibility()

    def _stop_level_meter(self) -> None:
        if self._level_meter is not None:
            try:
                self._level_meter.stop()
            except Exception:
                pass
            self._level_meter = None
        self._hold.reset()
        self.meter.setValue(0)

    # -- public API ------------------------------------------------------------------------

    def set_preset(self, preset: Preset) -> None:
        self._preset = preset
        if self._frames is not None:
            self._frames.set_preset(preset)

    @property
    def is_live(self) -> bool:
        return self._live

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start_live(self) -> None:
        if self._live:
            return
        port = self.port_combo.currentText()
        if not port:
            self._set_status(NO_PORTS_MSG)
            return
        clock = SessionClock()
        clock.start()
        backend = self._midi_backend_factory() if self._midi_backend_factory else None
        midi_in = MidiInput(port, clock, backend=backend)
        try:
            midi_in.open()
            if self._frames is None:
                self._frames = FrameSource(
                    Song(notes=(), duration=0.0), self._preset, WIDTH, HEIGHT
                )
        except Exception as exc:
            midi_in.close()
            self._set_status(f"Could not start live: {exc}")
            return
        self._clock, self._midi_in, self._state = clock, midi_in, LiveState()
        self._live = True
        self.live_button.setText("Stop live")
        self.record_button.setEnabled(True)
        self.port_combo.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self._timer.start()
        self._start_level_meter()
        self.tick()

    def stop_live(self) -> None:
        if not self._live:
            return
        if self._recording:
            self.stop_recording()
        self._timer.stop()
        self._stop_level_meter()
        self._meter_error = ""
        self._update_meter_visibility()
        if self._midi_in is not None:
            self._midi_in.close()
        self._midi_in = self._state = self._clock = None
        self._live = False
        self.live_button.setText("Start live")
        self.record_button.setEnabled(False)
        self.port_combo.setEnabled(True)
        self.refresh_button.setEnabled(True)
        if not self._error:
            self._set_status("Stopped")

    def start_recording(self) -> None:
        if not self._live or self._recording:
            return
        assert self._clock is not None and self._state is not None
        try:
            self._save_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            midi_path = self._save_dir / f"take-{stamp}.mid"
            wav_path = self._save_dir / f"take-{stamp}.wav"
            device = self.audio_combo.currentData()
            self._stop_level_meter()  # never open the same device twice
            self._clock.start()  # re-zero: MidiInput shares this clock object
            self._state.clear()
            recorder = None
            if device is not None:
                recorder = AudioRecorder(
                    wav_path, self._clock, device=device,
                    stream_factory=self._audio_stream_factory,
                )
                recorder.start()
        except Exception as exc:
            self._set_status(f"Could not start recording: {exc}")
            self._start_level_meter()
            return
        self._saved_note = ""
        self._recorder = recorder
        self._midi_path = midi_path
        self._wav_path = wav_path if recorder is not None else None
        self._recording = True
        self.record_button.setText("Stop recording")

    def stop_recording(self) -> None:
        if not self._recording:
            return
        assert self._clock is not None and self._state is not None and self._midi_in is not None
        end = self._clock.now()
        self._state.apply(self._midi_in.drain())
        self._recording = False
        self.record_button.setText("Record")
        recorder, self._recorder = self._recorder, None
        midi_path, wav_path = self._midi_path, self._wav_path
        assert midi_path is not None
        try:
            if recorder is not None:
                recorder.stop()
            save_midi(self._state.events, midi_path, end_time=end)
        except Exception as exc:
            self._set_status(f"Saving take failed: {exc}")
            self._start_level_meter()
            return
        self._start_level_meter()
        self._saved_note = f" — saved {midi_path.name}"
        self._set_status(f"Saved {midi_path}")
        self.take_saved.emit(midi_path, wav_path)

    def shutdown(self) -> None:
        """Stop everything (saving an active take) and release the renderer."""
        self.stop_live()
        self._timer.stop()
        if self._frames is not None:
            self._frames.close()
            self._frames = None

    def closeEvent(self, event: Any) -> None:
        self.shutdown()
        super().closeEvent(event)

    # -- per-frame update ------------------------------------------------------------------

    def tick(self) -> None:
        """Drain MIDI, render one frame, update meter and status."""
        if not self._live or self._frames is None:
            return
        assert self._clock and self._midi_in and self._state
        self._state.apply(self._midi_in.drain())
        t = self._clock.now()
        notes = self._state.visible_notes(t, keep_seconds=self._preset.seconds_visible * 1.5)
        data = self._frames.live_frame(notes, t)
        self.preview.set_frame(data, self._frames.width, self._frames.height)

        source = self._recorder or self._level_meter
        level = source.level() if source is not None else 0.0
        value, clipping = self._hold.update(level, self._time_fn())
        self.meter.setValue(value)
        self.meter.setStyleSheet(_METER_RED if clipping else "")

        count = sum(1 for e in self._state.events if e.kind == NOTE_ON)
        if self._recording:
            self._set_status(f"Recording {_fmt_time(t)} — {count} notes")
        else:
            extra = f" — {self._meter_error}" if self._meter_error else self._saved_note
            self._set_status(f"Live — {count} notes{extra}")

    # -- internals -------------------------------------------------------------------------

    def _toggle_live(self) -> None:
        self.stop_live() if self._live else self.start_live()

    def _toggle_record(self) -> None:
        self.stop_recording() if self._recording else self.start_recording()

    def _set_status(self, text: str) -> None:
        self._error = text if text.startswith(("Could not", "Saving")) else ""
        self.status_label.setText(text)

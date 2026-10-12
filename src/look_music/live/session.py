"""Record one live take: MIDI events and (optionally) line-in audio on a shared clock."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from look_music.live.audio_capture import AudioRecorder
from look_music.live.clock import SessionClock
from look_music.live.events import NOTE_ON, MidiEvent
from look_music.live.midi_input import MidiInput
from look_music.live.recorder import events_to_song, save_midi


@dataclass
class TakeResult:
    midi_path: Path
    audio_path: Path | None
    duration: float  # seconds (session end time)
    note_count: int
    audio_start_offset: float | None
    audio_overflows: int


def record_take(
    midi_path: str | Path,
    *,
    midi_port: str | int,
    audio_path: str | Path | None = None,
    audio_device: int | str | None = None,
    sample_rate: int = 48000,
    channels: int = 2,
    duration: float | None = None,
    stop_event: threading.Event | None = None,
    on_status: Callable[[float, int, float], None] | None = None,
    midi_backend: Any = None,
    audio_stream_factory: Callable[..., Any] | None = None,
    poll_interval: float = 0.05,
) -> TakeResult:
    """Record MIDI (and audio if `audio_path`) until `duration`, `stop_event` or Ctrl+C.

    `on_status(elapsed, notes_so_far, audio_level)` is called every poll. The MIDI file is
    always saved, even when stopped with Ctrl+C.
    """
    midi_path = Path(midi_path)
    clock = SessionClock()
    clock.start()
    recorder: AudioRecorder | None = None
    midi_in: MidiInput | None = None
    events: list[MidiEvent] = []
    notes = 0
    end_time = 0.0
    try:
        if audio_path is not None:
            recorder = AudioRecorder(
                audio_path, clock, device=audio_device, sample_rate=sample_rate,
                channels=channels, stream_factory=audio_stream_factory,
            )
            recorder.start()
        midi_in = MidiInput(midi_port, clock, backend=midi_backend)
        midi_in.open()

        try:
            while True:
                time.sleep(poll_interval)
                events.extend(midi_in.drain())
                elapsed = clock.now()
                if on_status is not None:
                    notes = sum(1 for e in events if e.kind == NOTE_ON)
                    on_status(elapsed, notes, recorder.level() if recorder else 0.0)
                if duration is not None and elapsed >= duration:
                    break
                if stop_event is not None and stop_event.is_set():
                    break
        except KeyboardInterrupt:
            pass  # finish cleanly: saving the take is the whole point

        end_time = clock.now()
        midi_in.close()
        events.extend(midi_in.drain())
        if recorder is not None:
            recorder.stop()
        save_midi(events, midi_path, end_time)
    finally:
        if midi_in is not None:
            midi_in.close()
        if recorder is not None:
            recorder.stop()

    return TakeResult(
        midi_path=midi_path,
        audio_path=Path(audio_path) if audio_path is not None else None,
        duration=end_time,
        note_count=len(events_to_song(events, end_time).notes),
        audio_start_offset=recorder.start_offset if recorder else None,
        audio_overflows=recorder.overflows if recorder else 0,
    )

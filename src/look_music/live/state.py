"""Live note accumulation: turns MidiEvents into notes for drawing and keeps them for saving."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from look_music.live.events import NOTE_OFF, NOTE_ON, SUSTAIN, MidiEvent


@dataclass(frozen=True)
class LiveNote:
    pitch: int
    velocity: int
    start: float  # session seconds
    end: float | None  # None while the key is held


class LiveState:
    """Accumulates live MidiEvents into notes for drawing and keeps every event for saving."""

    def __init__(self) -> None:
        self.events: list[MidiEvent] = []
        self.sustain = False
        self._open: dict[int, LiveNote] = {}
        self._released: list[LiveNote] = []

    def apply(self, events: Iterable[MidiEvent]) -> None:
        for ev in events:
            self.events.append(ev)
            if ev.kind == NOTE_ON:
                self._close(ev.pitch, ev.time)
                self._open[ev.pitch] = LiveNote(ev.pitch, ev.velocity, ev.time, None)
            elif ev.kind == NOTE_OFF:
                self._close(ev.pitch, ev.time)
            elif ev.kind == SUSTAIN:
                self.sustain = ev.velocity >= 64

    def _close(self, pitch: int, time: float) -> None:
        old = self._open.pop(pitch, None)
        if old is not None:
            self._released.append(LiveNote(old.pitch, old.velocity, old.start, time))

    def visible_notes(self, t: float, keep_seconds: float) -> list[LiveNote]:
        """Held notes plus released ones that ended after t - keep_seconds; prunes the rest."""
        cutoff = t - keep_seconds
        self._released = [n for n in self._released if n.end > cutoff]
        return self._released + list(self._open.values())

    def held_pitches(self) -> set[int]:
        return set(self._open)

    def clear(self) -> None:
        self.events.clear()
        self.sustain = False
        self._open.clear()
        self._released.clear()

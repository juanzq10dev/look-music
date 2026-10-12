"""Event type shared by live MIDI capture and downstream consumers."""

from __future__ import annotations

from dataclasses import dataclass

NOTE_ON, NOTE_OFF, SUSTAIN = "note_on", "note_off", "sustain"


@dataclass(frozen=True)
class MidiEvent:
    time: float  # seconds since session start (SessionClock)
    kind: str  # "note_on" | "note_off" | "sustain"
    pitch: int  # MIDI note number; 64 for sustain events
    velocity: int  # note velocity (note_on), 0 (note_off), or CC value 0-127 (sustain)

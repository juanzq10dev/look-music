"""Live MIDI input via python-rtmidi, timestamped on a SessionClock."""

from __future__ import annotations

import queue
from typing import Any

from look_music.live.clock import SessionClock
from look_music.live.events import NOTE_OFF, NOTE_ON, SUSTAIN, MidiEvent


def list_input_ports() -> list[str]:
    """Names of available MIDI input ports."""
    import rtmidi

    midi = rtmidi.MidiIn()
    try:
        return list(midi.get_ports())
    finally:
        del midi


def _resolve_port(port: str | int, names: list[str]) -> int:
    if isinstance(port, int):
        if not 0 <= port < len(names):
            raise ValueError(f"MIDI port index {port} out of range; available: {names}")
        return port
    if port in names:
        return names.index(port)
    matches = [i for i, n in enumerate(names) if port.lower() in n.lower()]
    if len(matches) == 1:
        return matches[0]
    problem = "ambiguous" if matches else "not found"
    raise ValueError(f"MIDI port {port!r} {problem}; available: {names}")


def parse_message(message: list[int], time: float) -> MidiEvent | None:
    """Convert a raw MIDI message to a MidiEvent, or None if irrelevant."""
    if len(message) < 3:
        return None
    status, d1, d2 = message[0], message[1], message[2]
    kind = status & 0xF0
    if kind == 0x90 and d2 > 0:
        return MidiEvent(time, NOTE_ON, d1, d2)
    if kind in (0x90, 0x80):
        return MidiEvent(time, NOTE_OFF, d1, 0)
    if kind == 0xB0 and d1 == 64:
        return MidiEvent(time, SUSTAIN, 64, d2)
    return None


class MidiInput:
    """Collects timestamped note/sustain events from a MIDI input port."""

    def __init__(self, port: str | int, clock: SessionClock, backend: Any = None):
        self.port = port
        self.clock = clock
        self._backend = backend
        self._queue: queue.SimpleQueue[MidiEvent] = queue.SimpleQueue()
        self._is_open = False

    def _on_message(self, event: tuple[list[int], float], data: Any = None) -> None:
        ev = parse_message(event[0], self.clock.now())
        if ev is not None:
            self._queue.put(ev)

    def open(self) -> None:
        if self._is_open:
            return
        if self._backend is None:
            import rtmidi

            self._backend = rtmidi.MidiIn()
        index = _resolve_port(self.port, list(self._backend.get_ports()))
        self._backend.ignore_types(sysex=True, timing=True, active_sense=True)
        self._backend.open_port(index)
        self._backend.set_callback(self._on_message)
        self._is_open = True

    def close(self) -> None:
        if not self._is_open:
            return
        self._backend.cancel_callback()
        self._backend.close_port()
        self._is_open = False

    def drain(self) -> list[MidiEvent]:
        """All events received since the last drain, in arrival order."""
        events: list[MidiEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                return events

    def __enter__(self) -> MidiInput:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

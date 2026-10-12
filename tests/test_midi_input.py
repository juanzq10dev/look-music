from __future__ import annotations

import pytest

from look_music.live.clock import SessionClock
from look_music.live.midi_input import MidiInput, list_input_ports


class FakeMidiIn:
    def __init__(self, ports=("Digital Piano", "Loop MIDI")):
        self.ports = list(ports)
        self.opened = None
        self.callback = None
        self.ignored = None
        self.closed = False

    def get_ports(self):
        return self.ports

    def open_port(self, i):
        self.opened = i

    def set_callback(self, fn):
        self.callback = fn

    def ignore_types(self, **kw):
        self.ignored = kw

    def cancel_callback(self):
        self.callback = None

    def close_port(self):
        self.closed = True

    def send(self, *msg):
        self.callback((list(msg), 0.0), None)


def make(port=0, ports=("Digital Piano", "Loop MIDI")):
    clock = SessionClock()
    clock.start()
    backend = FakeMidiIn(ports)
    return MidiInput(port, clock, backend), backend


def test_port_by_index():
    mi, be = make(1)
    mi.open()
    assert be.opened == 1
    assert be.ignored == dict(sysex=True, timing=True, active_sense=True)


def test_port_exact_name_beats_substring():
    mi, be = make("Piano", ports=("Piano 2", "Piano"))
    mi.open()
    assert be.opened == 1


def test_port_substring_case_insensitive():
    mi, be = make("loop")
    mi.open()
    assert be.opened == 1


def test_port_not_found():
    mi, _ = make("nope")
    with pytest.raises(ValueError, match="Digital Piano"):
        mi.open()


def test_port_ambiguous():
    mi, _ = make("piano", ports=("Piano A", "Piano B"))
    with pytest.raises(ValueError):
        mi.open()


def test_parsing():
    mi, be = make()
    with mi:
        be.send(0x90, 60, 100)
        be.send(0x90, 60, 0)
        be.send(0x80, 62, 40)
        be.send(0xB0, 64, 127)
        be.send(0xB0, 7, 50)
        be.send(0xF8)
        be.send(0x94, 65, 80)
        events = mi.drain()
    assert [(e.kind, e.pitch, e.velocity) for e in events] == [
        ("note_on", 60, 100),
        ("note_off", 60, 0),
        ("note_off", 62, 0),
        ("sustain", 64, 127),
        ("note_on", 65, 80),
    ]


def test_drain_empties_and_timestamps():
    mi, be = make()
    with mi:
        be.send(0x90, 60, 100)
        be.send(0x90, 61, 100)
        first = mi.drain()
        assert mi.drain() == []
    assert [e.pitch for e in first] == [60, 61]
    assert all(0 <= e.time < 1 for e in first)
    assert first[0].time <= first[1].time


def test_close_cancels_callback():
    mi, be = make()
    mi.open()
    mi.close()
    assert be.callback is None and be.closed


def test_list_input_ports_real_rtmidi():
    assert isinstance(list_input_ports(), list)

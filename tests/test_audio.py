"""Tests for the built-in synthesizer and WAV writer."""

from __future__ import annotations

import wave

import numpy as np

from look_music.audio import SAMPLE_RATE, synthesize, write_wav
from look_music.midi import Note, Song


def _single(pitch: int = 69, velocity: int = 100, length: float = 1.0) -> Song:
    note = Note(
        start=0.0, end=length, sound_end=length, pitch=pitch, velocity=velocity, track=0
    )
    return Song(notes=(note,), duration=length)


def test_length_matches_duration_plus_tail():
    song = _single(length=1.5)
    samples = synthesize(song, tail=2.0)
    expected = (song.duration + 2.0) * SAMPLE_RATE
    assert abs(len(samples) - expected) <= 1


def test_dtype_and_range():
    notes = tuple(
        Note(start=i * 0.1, end=i * 0.1 + 0.5, sound_end=i * 0.1 + 0.5, pitch=60 + i,
             velocity=127, track=0)
        for i in range(20)
    )
    song = Song(notes=notes, duration=2.5)
    samples = synthesize(song)
    assert samples.dtype == np.float32
    assert np.max(np.abs(samples)) <= 1.0


def test_empty_song_is_silent():
    song = Song(notes=(), duration=0.0)
    samples = synthesize(song, tail=1.0)
    assert len(samples) == SAMPLE_RATE
    assert np.all(samples == 0)


def test_a4_spectral_peak_near_440():
    samples = synthesize(_single(pitch=69, length=1.0))
    window = samples[: SAMPLE_RATE // 2]
    spectrum = np.abs(np.fft.rfft(window))
    freqs = np.fft.rfftfreq(len(window), 1.0 / SAMPLE_RATE)
    peak_freq = freqs[np.argmax(spectrum)]
    assert abs(peak_freq - 440.0) < 5.0


def test_louder_velocity_gives_larger_rms():
    quiet = synthesize(_single(velocity=40))
    loud = synthesize(_single(velocity=120))
    assert np.sqrt(np.mean(loud**2)) > np.sqrt(np.mean(quiet**2))


def test_write_wav_round_trip(tmp_path):
    samples = synthesize(_single(length=0.5), tail=0.5)
    path = tmp_path / "out.wav"
    write_wav(path, samples)

    with wave.open(str(path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == SAMPLE_RATE
        assert wf.getnframes() == len(samples)
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")

    assert np.max(np.abs(pcm / 32767.0 - samples)) < 1e-4

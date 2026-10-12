"""Piano audio: SoundFont rendering, a built-in additive synth fallback, and a mono WAV writer."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from look_music.midi import Song

SAMPLE_RATE = 44100
HARMONICS = 6
ATTACK_S = 0.005
RELEASE_S = 0.08
TAIL_AFTER_NOTE_S = 0.4
MAX_NOTE_S = 8.0
PEAK_TARGET = 0.89


def _render_note(
    start: float, sound_end: float, pitch: int, velocity: int, sample_rate: int, max_len: int
) -> np.ndarray:
    """Samples for one note, starting at its onset and at most `max_len` long."""
    held = max(sound_end - start, 0.0)
    length_s = min(held + TAIL_AFTER_NOTE_S, MAX_NOTE_S)
    n = min(int(length_s * sample_rate), max_len)
    t = np.arange(n) / sample_rate

    freq = 440.0 * 2.0 ** ((pitch - 69) / 12)
    base_decay = 1.0 + (pitch - 21) / 25
    wave_ = np.zeros(n)
    for h in range(1, HARMONICS + 1):
        if freq * h >= sample_rate / 2:
            continue
        decay = base_decay * (1.0 + 0.5 * (h - 1))
        wave_ += (h**-1.5) * np.sin(2 * np.pi * freq * h * t) * np.exp(-decay * t)

    attack = np.minimum(t / ATTACK_S, 1.0)
    release = np.exp(-np.maximum(t - held, 0.0) / RELEASE_S)
    amplitude = (velocity / 127) ** 1.5 * 0.2
    return amplitude * attack * release * wave_


def synthesize(song: Song, sample_rate: int = SAMPLE_RATE, tail: float = 2.0) -> np.ndarray:
    """Render the song to mono float32 samples in [-1, 1]; length = (song.duration + tail) * sample_rate."""
    total = int(round((song.duration + tail) * sample_rate))
    buf = np.zeros(total, dtype=np.float64)
    for note in song.notes:
        begin = int(note.start * sample_rate)
        if begin >= total:
            continue
        samples = _render_note(
            note.start, note.sound_end, note.pitch, note.velocity, sample_rate, total - begin
        )
        buf[begin : begin + len(samples)] += samples

    peak = float(np.max(np.abs(buf))) if total else 0.0
    if peak > PEAK_TARGET:
        buf *= PEAK_TARGET / peak
    return buf.astype(np.float32)


def render_soundfont(
    song: Song,
    soundfont: str | Path,
    sample_rate: int = SAMPLE_RATE,
    tail: float = 2.0,
    program: int = 0,
) -> np.ndarray:
    """Render the song with an SF2 piano; mono float32 in [-1, 1], same length rule as synthesize()."""
    import tinysoundfont

    path = Path(soundfont)
    if not path.is_file():
        raise FileNotFoundError(f"soundfont not found: {path}")

    total = int(round((song.duration + tail) * sample_rate))
    synth = tinysoundfont.Synth(samplerate=sample_rate)
    sfid = synth.sfload(str(path))
    synth.program_select(0, sfid, 0, program)

    # Note-off at sound_end (not end) so the sustain pedal extension is already applied.
    events: list[tuple[int, int, int, int]] = []  # (sample, 0=off / 1=on, pitch, velocity)
    for note in song.notes:
        on = int(round(note.start * sample_rate))
        if on >= total:
            continue
        events.append((on, 1, note.pitch, note.velocity))
        events.append((max(int(round(note.sound_end * sample_rate)), on), 0, note.pitch, 0))
    events.sort()

    buf = np.zeros((total, 2), dtype=np.float32)
    pos = 0

    def advance(to: int) -> None:
        nonlocal pos
        while pos < to:
            n = min(to - pos, sample_rate * 10)
            buf[pos : pos + n] = np.frombuffer(synth.generate(n), dtype=np.float32).reshape(n, 2)
            pos += n

    for sample, is_on, pitch, velocity in events:
        if sample >= total:
            break
        advance(sample)
        if is_on:
            synth.noteon(0, pitch, velocity)
        else:
            synth.noteoff(0, pitch)
    advance(total)

    mono = buf.mean(axis=1, dtype=np.float64)
    peak = float(np.max(np.abs(mono))) if total else 0.0
    if peak > PEAK_TARGET:
        mono *= PEAK_TARGET / peak
    return mono.astype(np.float32)


def write_wav(path: str | Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Write mono 16-bit PCM WAV."""
    clipped = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    pcm = np.round(clipped * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())

"""End-to-end audio/video sync: a recorded click must land on the frame its key lights up."""

from __future__ import annotations

import re
import subprocess
import wave
from pathlib import Path

import moderngl
import numpy as np
import pretty_midi
import pytest
from imageio_ffmpeg import get_ffmpeg_exe

from look_music.cli import render
from look_music.keyboard import key_layout
from look_music.preset import Preset

W, H, FPS = 320, 180, 30
LEAD_IN, TAIL = 2.0, 1.0
RATE = 48000
NOTE_START = 1.0
KEYBOARD_HEIGHT = Preset().keyboard_height


def _gl_available() -> bool:
    try:
        moderngl.create_standalone_context(require=330).release()
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _gl_available(), reason="no GL context")


def _make_midi(path: Path) -> None:
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=100, pitch=60, start=NOTE_START, end=1.5))
    pm.instruments.append(inst)
    pm.write(str(path))


def _make_click_wav(path: Path, seconds: float) -> None:
    samples = np.zeros(int(seconds * RATE), dtype="<i2")
    start = int(NOTE_START * RATE)
    samples[start : start + int(0.005 * RATE)] = 32767
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(samples.tobytes())


def _decode(mp4: Path, *args: str) -> bytes:
    cmd = [get_ffmpeg_exe(), "-loglevel", "error", "-i", str(mp4), *args, "-"]
    return subprocess.run(cmd, capture_output=True, check=True).stdout


def _audio_onset(mp4: Path) -> float:
    raw = _decode(mp4, "-map", "0:a", "-ac", "1", "-ar", str(RATE), "-f", "s16le")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.int32)
    loud = np.flatnonzero(np.abs(samples) > 8000)
    assert loud.size, "no click found in the decoded audio"
    return loud[0] / RATE


def _visual_onset(mp4: Path) -> float:
    raw = _decode(mp4, "-map", "0:v", "-f", "rawvideo", "-pix_fmt", "rgb24")
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, H, W, 3).astype(np.int32)
    layout = key_layout(W)
    x = int(layout.x[60] + layout.width[60] / 2)
    y = int(H * (1 - KEYBOARD_HEIGHT)) + 4  # just below the top of the keyboard
    pixels = frames[:, y, x, :]
    diff = np.abs(pixels - pixels[0]).sum(axis=1)
    lit = np.flatnonzero(diff > 60)
    assert lit.size, "middle C never lit up"
    return lit[0] / FPS


def _duration(mp4: Path) -> float:
    out = subprocess.run(
        [get_ffmpeg_exe(), "-i", str(mp4)], capture_output=True, text=True, errors="replace"
    ).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def _render(tmp_path: Path, wav_seconds: float, audio_offset: float = 0.0) -> tuple[Path, int]:
    midi = tmp_path / "in.mid"
    wav = tmp_path / "take.wav"
    _make_midi(midi)
    _make_click_wav(wav, wav_seconds)
    out = tmp_path / "out.mp4"
    frames = render(
        midi, out, width=W, height=H, fps=FPS, preset=Preset(bloom=False),
        lead_in=LEAD_IN, tail=TAIL, crf=18, audio=True, audio_file=wav,
        audio_offset=audio_offset,
    )
    return out, frames


@pytest.mark.parametrize("offset", [0.0, 0.1, -0.1])
def test_audio_and_visual_onsets_align(tmp_path: Path, offset: float) -> None:
    out, _ = _render(tmp_path, 3.0, offset)
    expected = LEAD_IN + NOTE_START + offset
    audio = _audio_onset(out)
    visual = _visual_onset(out)
    print(f"offset={offset}: audio onset {audio:.4f}s, visual onset {visual:.4f}s")
    assert audio == pytest.approx(expected, abs=1 / FPS)
    assert visual == pytest.approx(LEAD_IN + NOTE_START, abs=1 / FPS)
    assert abs(audio - (visual + offset)) <= 1 / FPS


@pytest.mark.parametrize("wav_seconds", [3.0, 10.0])
def test_duration_is_exactly_video_length(tmp_path: Path, wav_seconds: float) -> None:
    out, frames = _render(tmp_path, wav_seconds)
    assert _duration(out) == pytest.approx(frames / FPS, abs=1024 / RATE + 0.01)
    audio_len = len(_decode(out, "-map", "0:a", "-ac", "1", "-ar", str(RATE), "-f", "s16le")) / 2
    assert audio_len / RATE == pytest.approx(frames / FPS, abs=0.05)

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from imageio_ffmpeg import get_ffmpeg_exe

from look_music.export import VideoWriter

WIDTH, HEIGHT, FPS, FRAMES = 64, 48, 10, 10


def _frame(i: int) -> bytes:
    return np.full((HEIGHT, WIDTH, 3), i * 20 % 256, dtype=np.uint8).tobytes()


def _probe(path: Path) -> str:
    result = subprocess.run(
        [get_ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True, errors="replace"
    )
    return result.stderr


def _write_wav(path: Path) -> None:
    rate = 44100
    t = np.arange(rate) / rate
    samples = (np.sin(2 * np.pi * 440 * t) * 0.3 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_writes_h264_mp4(tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    with VideoWriter(out, WIDTH, HEIGHT, FPS) as w:
        for i in range(FRAMES):
            w.write(_frame(i))
    assert w.frames_written == FRAMES
    assert out.stat().st_size > 0
    info = _probe(out)
    assert "Video: h264" in info
    assert "64x48" in info


def test_wrong_frame_size_raises(tmp_path: Path) -> None:
    with VideoWriter(tmp_path / "out.mp4", WIDTH, HEIGHT, FPS) as w:
        with pytest.raises(ValueError):
            w.write(b"\0" * 10)


def test_odd_width_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        VideoWriter(tmp_path / "out.mp4", 63, HEIGHT, FPS)


def test_audio_track_is_muxed(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _write_wav(wav)
    out = tmp_path / "out.mp4"
    with VideoWriter(out, WIDTH, HEIGHT, FPS, audio_path=wav) as w:
        for i in range(FRAMES):
            w.write(_frame(i))
    info = _probe(out)
    assert "Audio: aac" in info
    assert "Video: h264" in info


def test_context_manager_closes_process(tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    writer = VideoWriter(out, WIDTH, HEIGHT, FPS)
    with writer:
        writer.write(_frame(0))
    assert writer._proc.poll() == 0
    assert writer._closed
    assert "Video: h264" in _probe(out)


def test_context_manager_does_not_mask_exception(tmp_path: Path) -> None:
    writer = None
    with pytest.raises(KeyError):
        with VideoWriter(tmp_path / "out.mp4", WIDTH, HEIGHT, FPS) as writer:
            writer.write(_frame(0))
            raise KeyError("boom")
    assert writer is not None and writer._proc.poll() is not None


def _af(cmd: list[str]) -> str:
    return cmd[cmd.index("-af") + 1]


def test_positive_audio_offset_uses_adelay(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _write_wav(wav)
    out = tmp_path / "out.mp4"
    with VideoWriter(
        out, WIDTH, HEIGHT, FPS, audio_path=wav, audio_offset=0.25, duration=FRAMES / FPS
    ) as w:
        cmd = w.command
        for i in range(FRAMES):
            w.write(_frame(i))
    assert "-itsoffset" not in cmd
    assert _af(cmd) == "adelay=delays=250.000:all=1,apad"
    assert float(cmd[cmd.index("-t") + 1]) == pytest.approx(FRAMES / FPS)
    assert "-shortest" not in cmd
    assert "Audio: aac" in _probe(out)


def test_negative_audio_offset_uses_atrim(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _write_wav(wav)
    out = tmp_path / "out.mp4"
    with VideoWriter(
        out, WIDTH, HEIGHT, FPS, audio_path=wav, audio_offset=-0.25, duration=FRAMES / FPS
    ) as w:
        cmd = w.command
        for i in range(FRAMES):
            w.write(_frame(i))
    assert "-itsoffset" not in cmd
    assert _af(cmd) == "atrim=start=0.250000,asetpts=PTS-STARTPTS,apad"
    assert "Audio: aac" in _probe(out)


def test_no_duration_falls_back_to_shortest(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _write_wav(wav)
    with VideoWriter(tmp_path / "out.mp4", WIDTH, HEIGHT, FPS, audio_path=wav) as w:
        cmd = w.command
        for i in range(FRAMES):
            w.write(_frame(i))
    assert "-shortest" in cmd and "-t" not in cmd
    assert _af(cmd) == "apad"


def test_short_audio_does_not_break_pipe(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _write_wav(wav)  # 1 s of audio, 5 s of video
    out = tmp_path / "out.mp4"
    with VideoWriter(out, WIDTH, HEIGHT, FPS, audio_path=wav, duration=5.0) as w:
        for i in range(5 * FPS):
            w.write(_frame(i))
    assert "Audio: aac" in _probe(out)


def test_no_audio_offset_by_default(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _write_wav(wav)
    with VideoWriter(tmp_path / "out.mp4", WIDTH, HEIGHT, FPS, audio_path=wav) as w:
        assert "-itsoffset" not in w.command
        for i in range(FRAMES):
            w.write(_frame(i))

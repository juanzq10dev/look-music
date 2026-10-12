from __future__ import annotations

import math
import subprocess

import imageio_ffmpeg
import moderngl
import pretty_midi
import pytest

from look_music.cli import main, render
from look_music.preset import Preset

W, H, FPS = 160, 90, 10
LEAD_IN, TAIL = 0.5, 0.5
SONG_DURATION = 1.5  # last note ends at 1.5 s


def _gl_available() -> bool:
    try:
        moderngl.create_standalone_context(require=330).release()
    except Exception:
        return False
    return True


needs_gl = pytest.mark.skipif(not _gl_available(), reason="no GL context")


@pytest.fixture
def midi_path(tmp_path):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=0.7))
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=67, start=0.5, end=SONG_DURATION))
    pm.instruments.append(inst)
    path = tmp_path / "in.mid"
    pm.write(str(path))
    return path


def _probe(path) -> str:
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True
    )
    return result.stderr


def _render(midi_path, out, audio=True, progress=None):
    return render(
        midi_path, out, width=W, height=H, fps=FPS, preset=Preset(),
        lead_in=LEAD_IN, tail=TAIL, crf=28, audio=audio, progress=progress,
    )


@needs_gl
def test_render_with_audio(midi_path, tmp_path):
    out = tmp_path / "out.mp4"
    calls = []
    frames = _render(midi_path, out, progress=lambda done, total: calls.append((done, total)))
    expected = math.ceil((SONG_DURATION + LEAD_IN + TAIL) * FPS)
    assert frames == expected
    assert calls[-1] == (expected, expected)
    info = _probe(out)
    assert "Video: h264" in info
    assert "160x90" in info
    assert "Audio: aac" in info


@needs_gl
def test_render_no_audio(midi_path, tmp_path):
    out = tmp_path / "out.mp4"
    _render(midi_path, out, audio=False)
    info = _probe(out)
    assert "Video: h264" in info
    assert "Audio:" not in info


@needs_gl
def test_main_ok(midi_path, tmp_path):
    out = tmp_path / "out.mp4"
    code = main([
        "render", str(midi_path), "-o", str(out), "--width", str(W), "--height", str(H),
        "--fps", str(FPS), "--lead-in", str(LEAD_IN), "--tail", str(TAIL),
        "--crf", "28", "--no-audio",
    ])
    assert code == 0
    assert out.stat().st_size > 0


def test_missing_input(tmp_path, capsys):
    code = main(["render", str(tmp_path / "nope.mid"), "-o", str(tmp_path / "o.mp4")])
    assert code == 2
    assert capsys.readouterr().err.startswith("error:")


def test_odd_width(midi_path, tmp_path, capsys):
    code = main(["render", str(midi_path), "-o", str(tmp_path / "o.mp4"), "--width", "161"])
    assert code == 2
    assert capsys.readouterr().err.startswith("error:")


def test_invalid_preset(midi_path, tmp_path, capsys):
    bad = tmp_path / "p.json"
    bad.write_text("{not json")
    code = main(["render", str(midi_path), "-o", str(tmp_path / "o.mp4"), "--preset", str(bad)])
    assert code == 2
    assert capsys.readouterr().err.startswith("error:")


def test_unreadable_midi(tmp_path, capsys):
    bad = tmp_path / "bad.mid"
    bad.write_bytes(b"not a midi file")
    code = main(["render", str(bad), "-o", str(tmp_path / "o.mp4")])
    assert code == 2
    assert capsys.readouterr().err.startswith("error:")

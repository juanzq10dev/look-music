"""Command-line interface: `look-music render INPUT.mid -o OUTPUT.mp4`."""

from __future__ import annotations

import argparse
import math
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from look_music.audio import synthesize, write_wav
from look_music.export import VideoWriter
from look_music.keyboard import key_layout
from look_music.midi import load_midi
from look_music.preset import Preset, load_preset
from look_music.render.gl import Renderer
from look_music.render.scene import build_instances, prepare_notes

PROGRESS_INTERVAL = 0.25  # seconds between progress line updates


def render(
    input_path: str | Path,
    output_path: str | Path,
    *,
    width: int,
    height: int,
    fps: int,
    preset: Preset,
    lead_in: float,
    tail: float,
    crf: int,
    audio: bool,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """Render a MIDI file to an MP4; return the number of frames written."""
    song = load_midi(input_path).shifted(lead_in)
    notes = prepare_notes(song)
    layout = key_layout(width)
    total_frames = math.ceil((song.duration + tail) * fps)

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = None
        if audio:
            audio_path = Path(tmp) / "audio.wav"
            write_wav(audio_path, synthesize(song, tail=tail))
        with Renderer(width, height, preset.background) as renderer, VideoWriter(
            output_path, width, height, fps, audio_path=audio_path, crf=crf
        ) as writer:
            for k in range(total_frames):
                instances = build_instances(notes, k / fps, width, height, layout, preset)
                writer.write(renderer.render(instances))
                if progress:
                    progress(k + 1, total_frames)
    return total_frames


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="look-music")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("render", help="render a MIDI file to a falling-note video")
    p.add_argument("input", type=Path, help="input MIDI file")
    p.add_argument("-o", "--output", type=Path, required=True, help="output MP4 file")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=60)
    p.add_argument("--preset", type=Path, help="JSON preset file")
    p.add_argument("--lead-in", type=float, default=2.0, help="seconds before the first note")
    p.add_argument("--tail", type=float, default=2.0, help="seconds after the last note")
    p.add_argument("--crf", type=int, default=18, help="x264 quality (lower is better)")
    p.add_argument("--no-audio", action="store_true", help="omit the synthesized audio track")
    return parser


def _error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2:
        return _error(f"width and height must be positive and even, got {args.width}x{args.height}")
    if args.fps <= 0:
        return _error(f"fps must be greater than 0, got {args.fps}")
    if args.lead_in < 0 or args.tail < 0:
        return _error("lead-in and tail must not be negative")
    if not args.input.is_file():
        return _error(f"input file not found: {args.input}")

    try:
        preset = load_preset(args.preset) if args.preset else Preset()
    except OSError as exc:
        return _error(f"cannot read preset: {exc}")
    except (ValueError, TypeError) as exc:  # includes json.JSONDecodeError
        return _error(f"invalid preset {args.preset}: {exc}")

    start = time.monotonic()
    last_print = 0.0
    printed = False

    def progress(done: int, total: int) -> None:
        nonlocal last_print, printed
        now = time.monotonic()
        if done != total and now - last_print < PROGRESS_INTERVAL:
            return
        last_print = now
        printed = True
        speed = done / max(now - start, 1e-9)
        pct = 100 * done / total if total else 100.0
        print(f"\r{pct:5.1f}%  {done}/{total} frames  {speed:.1f} fps", end="", file=sys.stderr, flush=True)

    try:
        frames = render(
            args.input, args.output,
            width=args.width, height=args.height, fps=args.fps, preset=preset,
            lead_in=args.lead_in, tail=args.tail, crf=args.crf,
            audio=not args.no_audio, progress=progress,
        )
    except Exception as exc:
        if printed:
            print(file=sys.stderr)
        return _error(str(exc) or type(exc).__name__)

    if printed:
        print(file=sys.stderr)
    print(f"wrote {args.output} ({frames} frames) in {time.monotonic() - start:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

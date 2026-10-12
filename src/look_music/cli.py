"""Command-line interface: `look-music render INPUT.mid -o OUTPUT.mp4`."""

from __future__ import annotations

import argparse
import dataclasses
import math
import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from look_music.audio import render_soundfont, synthesize, write_wav
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
    soundfont: Path | None = None,
    audio_file: Path | None = None,
    audio_offset: float = 0.0,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """Render a MIDI file to an MP4; return the number of frames written.

    A recorded `audio_file` starts at the same instant as the MIDI file, so it is delayed by
    `lead_in` (the video is shifted by that much); `audio_offset` is a further manual correction.
    """
    song = load_midi(input_path).shifted(lead_in)
    notes = prepare_notes(song, preset)
    layout = key_layout(width)
    total_frames = math.ceil((song.duration + tail) * fps)

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = audio_file
        delay = lead_in + audio_offset if audio_file is not None else 0.0
        if audio and audio_file is None:
            audio_path = Path(tmp) / "audio.wav"
            samples = (
                render_soundfont(song, soundfont, tail=tail)
                if soundfont
                else synthesize(song, tail=tail)
            )
            write_wav(audio_path, samples)
        with Renderer(
            width, height, preset.background, bloom=preset.bloom_settings()
        ) as renderer, VideoWriter(
            output_path, width, height, fps, audio_path=audio_path, crf=crf,
            audio_offset=delay,
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
    p.add_argument(
        "--soundfont", type=Path,
        help="SF2 SoundFont for piano audio (default: $LOOK_MUSIC_SOUNDFONT, else built-in synth)",
    )
    p.add_argument(
        "--audio", type=Path, metavar="FILE",
        help="use this audio file (e.g. a recorded WAV) as the soundtrack instead of synthesizing",
    )
    p.add_argument(
        "--audio-offset", type=float, default=0.0, metavar="SECONDS",
        help="shift --audio relative to the notes: positive delays it, negative advances it",
    )
    p.add_argument("--no-bloom", action="store_true", help="disable the glow, regardless of preset")

    sub.add_parser("devices", help="list MIDI input ports and audio input devices")

    r = sub.add_parser("record", help="record a take from a MIDI keyboard (and line-in audio)")
    r.add_argument("output", type=Path, help="output MIDI file")
    r.add_argument("--audio", type=Path, metavar="OUT.wav", help="also record audio to this WAV file")
    r.add_argument("--midi-port", metavar="NAME_OR_INDEX", help="MIDI input port (default: the only one)")
    r.add_argument("--audio-device", metavar="NAME_OR_INDEX", help="audio input device (default: system default)")
    r.add_argument("--sample-rate", type=int, default=48000)
    r.add_argument("--channels", type=int, default=2)
    r.add_argument("--duration", type=float, metavar="SECONDS", help="stop automatically after this long")
    return parser


def _error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


NO_PORTS_HINT = "no MIDI input ports found - is the piano connected by USB and switched on?"
METER_WIDTH = 20
STATUS_INTERVAL = 0.1  # seconds between record status line updates


def _index_or_name(value: str) -> int | str:
    return int(value) if value.strip().isdigit() else value


def _devices() -> int:
    from look_music.live.audio_capture import list_input_devices
    from look_music.live.midi_input import list_input_ports

    ports = list_input_ports()
    print("MIDI input ports:")
    if ports:
        for i, name in enumerate(ports):
            print(f"  {i}: {name}")
    else:
        print(f"  {NO_PORTS_HINT}")
    print("Audio input devices:")
    devices = list_input_devices()
    if devices:
        for i, name in devices:
            print(f"  {i}: {name}")
    else:
        print("  none found")
    return 0


def _format_status(elapsed: float, notes: int, level: float, with_audio: bool) -> str:
    minutes, seconds = divmod(int(elapsed), 60)
    line = f"{minutes:02d}:{seconds:02d}  notes: {notes:4d}"
    if with_audio:
        filled = min(METER_WIDTH, round(level * METER_WIDTH))
        line += f"  [{'#' * filled}{'-' * (METER_WIDTH - filled)}]"
        line += " CLIP" if level >= 0.99 else "     "
    return line


def _record(args: argparse.Namespace) -> int:
    from look_music.live.midi_input import list_input_ports
    from look_music.live.session import record_take

    if args.duration is not None and args.duration <= 0:
        return _error(f"duration must be greater than 0, got {args.duration}")
    if args.sample_rate <= 0 or args.channels <= 0:
        return _error("sample rate and channels must be greater than 0")
    if args.audio is None and (args.audio_device is not None):
        return _error("--audio-device requires --audio")

    ports = list_input_ports()
    if args.midi_port is not None:
        port: str | int = _index_or_name(args.midi_port)
    elif not ports:
        return _error(NO_PORTS_HINT)
    elif len(ports) == 1:
        port = 0
    else:
        listing = ", ".join(f"{i}: {n}" for i, n in enumerate(ports))
        return _error(f"several MIDI input ports found, choose one with --midi-port ({listing})")
    device = _index_or_name(args.audio_device) if args.audio_device is not None else None

    with_audio = args.audio is not None
    last_print = 0.0
    printed = False

    def on_status(elapsed: float, notes: int, level: float) -> None:
        nonlocal last_print, printed
        now = time.monotonic()
        if now - last_print < STATUS_INTERVAL:
            return
        last_print = now
        printed = True
        print("\r" + _format_status(elapsed, notes, level, with_audio), end="", file=sys.stderr, flush=True)

    print("Recording... press Ctrl+C to stop", file=sys.stderr)
    try:
        result = record_take(
            args.output, midi_port=port, audio_path=args.audio, audio_device=device,
            sample_rate=args.sample_rate, channels=args.channels, duration=args.duration,
            on_status=on_status,
        )
    except Exception as exc:
        if printed:
            print(file=sys.stderr)
        return _error(str(exc) or type(exc).__name__)
    if printed:
        print(file=sys.stderr)

    minutes, seconds = divmod(result.duration, 60)
    print(f"recorded {result.note_count} notes in {int(minutes):02d}:{seconds:04.1f} -> {result.midi_path}")
    if result.audio_path is not None:
        offset = result.audio_start_offset or 0.0
        print(f"audio: {result.audio_path} (start offset {offset * 1000:.1f} ms)")
        if result.audio_overflows:
            print(
                f"warning: {result.audio_overflows} audio buffer overflow(s) - the recording may have gaps",
                file=sys.stderr,
            )
    render_cmd = f"look-music render {result.midi_path}"
    if result.audio_path is not None:
        render_cmd += f" --audio {result.audio_path}"
    print(f"next: {render_cmd} -o {result.midi_path.with_suffix('.mp4')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "devices":
        return _devices()
    if args.command == "record":
        return _record(args)
    return _render_command(args)


def _render_command(args: argparse.Namespace) -> int:
    if args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2:
        return _error(f"width and height must be positive and even, got {args.width}x{args.height}")
    if args.fps <= 0:
        return _error(f"fps must be greater than 0, got {args.fps}")
    if args.lead_in < 0 or args.tail < 0:
        return _error("lead-in and tail must not be negative")
    if not args.input.is_file():
        return _error(f"input file not found: {args.input}")

    if args.audio is not None and args.no_audio:
        return _error("--audio and --no-audio cannot be used together")
    if args.audio is not None and not args.audio.is_file():
        return _error(f"audio file not found: {args.audio}")

    if args.audio_offset and args.audio is None:
        return _error("--audio-offset requires --audio")

    soundfont = args.soundfont
    if soundfont is None and os.environ.get("LOOK_MUSIC_SOUNDFONT"):
        soundfont = Path(os.environ["LOOK_MUSIC_SOUNDFONT"])
    if soundfont is not None and not soundfont.is_file():
        return _error(f"soundfont not found: {soundfont}")

    try:
        preset = load_preset(args.preset) if args.preset else Preset()
    except OSError as exc:
        return _error(f"cannot read preset: {exc}")
    except (ValueError, TypeError) as exc:  # includes json.JSONDecodeError
        return _error(f"invalid preset {args.preset}: {exc}")
    if args.no_bloom:
        preset = dataclasses.replace(preset, bloom=False)

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
            audio=not args.no_audio, soundfont=soundfont,
            audio_file=args.audio, audio_offset=args.audio_offset, progress=progress,
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

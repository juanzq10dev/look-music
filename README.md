# look-music

Render MIDI files into falling-note piano videos (Synthesia / SeeMusic style), fully offline.

Every frame is rendered on the GPU (moderngl, headless) and streamed into ffmpeg, so output is
deterministic and never drops frames, regardless of machine speed.

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). ffmpeg is bundled via `imageio-ffmpeg`.

```sh
uv sync
```

## Usage

```sh
uv run look-music render song.mid -o song.mp4
```

| Option | Default | Description |
|---|---|---|
| `--width`, `--height` | 1920 × 1080 | Output size (must be even) |
| `--fps` | 60 | Frame rate |
| `--preset FILE` | built-in | JSON preset (see below) |
| `--lead-in` | 2.0 | Seconds before the first note, so notes fall in from the top |
| `--tail` | 2.0 | Seconds after the last note |
| `--crf` | 18 | x264 quality, lower is better |
| `--no-audio` | off | Omit the synthesized audio track |

### Presets

A preset is a JSON object; any field left out keeps its default (see `src/look_music/preset.py`):

```json
{
  "background": "#0B0B10",
  "track_colors": ["#4FC3F7", "#F06292"],
  "seconds_visible": 3.0,
  "keyboard_height": 0.16
}
```

## Development

```sh
uv run pytest
```

| Module | Role |
|---|---|
| `midi.py` | MIDI → time-sorted notes, sustain pedal |
| `keyboard.py` | 88-key geometry |
| `preset.py` | Colours and sizes |
| `render/scene.py` | Time *t* → list of rounded rectangles |
| `render/gl.py` | Offscreen GPU rasteriser |
| `audio.py` | Built-in piano-like synth → WAV |
| `export.py` | Frames + audio → MP4 via ffmpeg |
| `cli.py` | Command-line entry point |

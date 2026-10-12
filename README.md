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
| `--no-audio` | off | Omit the audio track |
| `--soundfont PATH` | `$LOOK_MUSIC_SOUNDFONT`, else built-in synth | SF2 SoundFont used for piano audio (see [Audio](#audio)) |
| `--no-bloom` | off | Disable the glow around notes, regardless of the preset |

### Audio

By default the audio track comes from a small built-in additive synth. For a realistic piano, pass an
SF2 SoundFont with `--soundfont PATH` or set the `LOOK_MUSIC_SOUNDFONT` environment variable
(the flag wins if both are set):

```sh
set LOOK_MUSIC_SOUNDFONT=C:\soundfonts\GeneralUser-GS.sf2
uv run look-music render song.mid -o song.mp4
```

(In PowerShell use `$env:LOOK_MUSIC_SOUNDFONT = "C:\soundfonts\GeneralUser-GS.sf2"` instead.)

We recommend **GeneralUser GS** (https://github.com/mrbumpy409/GeneralUser-GS), a free,
general-purpose SoundFont with a good piano preset. Any SF2 file works; the piano is program 0
(Acoustic Grand Piano).

If no SoundFont is given, the built-in synth is used. It needs no extra files, but sounds much
more basic than a sampled piano.

### Presets

A preset is a JSON object; any field left out keeps its default (see `src/look_music/preset.py`).
Unknown field names are an error, so typos are caught early.

| Field | Default | Description |
|---|---|---|
| `background`, `white_key`, `black_key`, `keyboard_edge` | `#0B0B10`, `#F2F2F2`, `#161616`, `#8B1A1A` | `#RRGGBB` colours |
| `track_colors` | five colours | `#RRGGBB` list used in `track` mode, cycled by track index |
| `keyboard_height` | 0.16 | Keyboard height as a fraction of the frame height |
| `seconds_visible` | 3.0 | Seconds a note takes to fall from the top to the keys |
| `note_radius`, `note_gap` | 6.0, 2.0 | Corner radius and horizontal inset of notes, in pixels at 1080p |
| `black_note_darkness` | 0.75 | Brightness multiplier for notes over black keys |
| `min_velocity_brightness` | 0.6 | Brightness of a velocity-0 note (velocity 127 is full brightness) |
| `color_mode` | `"auto"` | How notes are coloured (see below) |
| `hand_split` | 60 | MIDI pitch below which a note is left hand (60 = middle C) |
| `left_hand_color`, `right_hand_color` | `#F06292`, `#4FC3F7` | `#RRGGBB` colours for `hand` mode |
| `pitch_colors` | 12 hues | Exactly 12 `#RRGGBB` colours, pitch classes C through B |
| `bloom` | `true` | Add a soft glow around notes |
| `bloom_intensity` | 0.9 | Glow strength; 0 is no visible glow, must not be negative |
| `bloom_radius` | 24.0 | Glow blur radius in pixels at 1080p (scales with frame height); must be greater than 0 |

**Colour modes**

- `track`: each track gets the colour at its index in `track_colors` (wrapping around).
- `hand`: notes below `hand_split` use `left_hand_color`, the rest use `right_hand_color`.
- `pitch`: each note takes `pitch_colors[pitch % 12]`, so every C is the same colour, every C# another, and so on.
- `auto` (default): `track` if the MIDI file has two or more tracks, otherwise `hand`.

**Example** (every field shown; you only need the ones you want to change):

```json
{
  "background": "#0B0B10",
  "white_key": "#F2F2F2",
  "black_key": "#161616",
  "keyboard_edge": "#8B1A1A",
  "track_colors": ["#4FC3F7", "#F06292", "#81C784", "#FFB74D", "#BA68C8"],
  "keyboard_height": 0.16,
  "seconds_visible": 3.0,
  "note_radius": 6.0,
  "note_gap": 2.0,
  "black_note_darkness": 0.75,
  "min_velocity_brightness": 0.6,
  "color_mode": "hand",
  "hand_split": 60,
  "left_hand_color": "#F06292",
  "right_hand_color": "#4FC3F7",
  "pitch_colors": [
    "#FF4D4D", "#FF8C1A", "#FFD11A", "#B3E61A", "#33CC33", "#1AD1A6",
    "#1AB3FF", "#3366FF", "#8C4DFF", "#D94DFF", "#FF4DB8", "#FF667F"
  ],
  "bloom": true,
  "bloom_intensity": 0.9,
  "bloom_radius": 24.0
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
| `preset.py` | Colours, sizes, colour modes and bloom settings |
| `render/scene.py` | Time *t* → list of rounded rectangles |
| `render/gl.py` | Offscreen GPU rasteriser; optional bloom (separable Gaussian glow composited over the scene) |
| `audio.py` | SF2 SoundFont rendering via tinysoundfont, built-in piano-like synth fallback, WAV output |
| `export.py` | Frames + audio → MP4 via ffmpeg |
| `cli.py` | Command-line entry point |

# look-music

Render MIDI files into falling-note piano videos (Synthesia / SeeMusic style), fully offline.

Every frame is rendered on the GPU (moderngl, headless) and streamed into ffmpeg, so output is
deterministic and never drops frames, regardless of machine speed.

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). ffmpeg is bundled via `imageio-ffmpeg`.

```sh
uv sync
```

## Desktop app

```sh
uv run look-music gui
uv run look-music gui song.mid
```

The desktop app has a **Playback** tab and a **Live** tab, plus a **Settings** panel on the right.
Open a MIDI file with File > Open MIDI… (Ctrl+O).

**Playback** previews a MIDI file with sound, and exports it to video.

- Play/pause with the button or Space; drag the seek slider to move through the song.
- Audio source: *Built-in synth*, *SoundFont…* (an SF2 file; starts from `LOOK_MUSIC_SOUNDFONT` if set), or *Audio file…* (a WAV, such as a recording).
- The preview is always rendered at 1280 × 720.
- File > Load preset… and File > Save preset… read and write JSON presets.

**Settings** edits the current preset, and the preview updates as you change it:

- Colour mode (auto, track, hand, pitch) and the left-hand, right-hand and background colours
- Fall time (1–8 s) and keyboard height
- Bloom on/off, bloom intensity and bloom radius

**Export** (File > Export video…) asks for an output file (defaults to the MIDI name with `.mp4`),
a resolution (1280 × 720, 1920 × 1080 or 3840 × 2160) and a frame rate (30 or 60). A progress
dialog shows the render. Cancel stops it and deletes the partial file. The export uses the audio
source selected in Playback.

**Live** works with a keyboard connected by USB, with its sound on line-in (see
[Recording from a digital piano](#recording-from-a-digital-piano)).

- Pick the MIDI port and the audio input. Refresh rescans them, for example after plugging in the piano.
- **Start live** shows the notes rising from the keys as you play; **Stop live** ends it.
- The level meter appears when an audio input is selected and moves with its signal. The bar rises
  at once and falls back slowly. It turns red for a second when the input reaches full scale (clipping).
- **Record** starts a take and the button becomes **Stop recording**. Stopping saves the take and
  opens it in Playback, ready to export.
- Takes are saved to `~/Music/look-music/` as `take-YYYYMMDD-HHMMSS.mid`, with a matching `.wav`
  when an audio input was selected. When a take is opened, its WAV becomes the audio source, so the
  export uses the real recording.

**Typical workflow**

1. Connect the piano to the PC by USB, and run a cable from its headphone/line output into the PC's line-in.
2. Run `uv run look-music gui` and open the **Live** tab. Choose the MIDI port and the audio input.
3. Click **Start live**, play, and check that the meter moves without going red. Adjust the input level if needed.
4. Click **Record**, play the piece, then click **Stop recording**. The take opens in Playback.
5. Choose File > Export video…

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
| `--audio FILE` | synthesized | Use this audio file (e.g. a recording from `look-music record`) as the soundtrack |
| `--audio-offset SECONDS` | 0 | With `--audio`: positive delays the audio, negative advances it (sync correction) |
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

### Recording from a digital piano

Connect the piano to the PC with USB (MIDI) and run a cable from its headphone/line output into
the PC's line-in or microphone jack (aux), so its real sound is captured too.

```sh
uv run look-music devices
uv run look-music record take.mid --audio take.wav
```

`devices` lists the MIDI input ports and audio input devices. `record` uses the only MIDI port if
there is exactly one; otherwise choose with `--midi-port` (name or index) and, for audio,
`--audio-device` (name or index). Press Ctrl+C to stop; the take is saved either way. Then render it:

```sh
uv run look-music render take.mid --audio take.wav -o take.mp4
```

While recording, a status line shows elapsed time, notes played and a level meter. Check that the
meter moves when you play, and that it does not show `CLIP` (lower the input volume if it does).
If the sound and the falling notes are slightly out of step, shift the audio with
`--audio-offset` (positive delays it, negative advances it), e.g. `--audio-offset -0.04`.

| Command / option | Default | Description |
|---|---|---|
| `devices` | | List MIDI input ports and audio input devices |
| `record OUT.mid` | | Record MIDI from a keyboard |
| `--audio OUT.wav` | off | Also record line-in audio to this WAV file |
| `--midi-port NAME_OR_INDEX` | the only port | MIDI input port |
| `--audio-device NAME_OR_INDEX` | system default | Audio input device |
| `--sample-rate`, `--channels` | 48000, 2 | Audio format |
| `--duration SECONDS` | until Ctrl+C | Stop automatically |

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
| `live/` | Live capture: MIDI input, line-in audio recorder and level meter, shared session clock, live note state, `.mid` writer, `record_take` session loop |
| `preview/` | Desktop app playback: `frames.py` preview frame source, `player.py` play/pause/seek clock with synced WAV playback |
| `gui/` | Desktop app (PySide6): `app.py` entry point, `main_window.py`, `playback_tab.py`, `live_tab.py`, `settings_panel.py`, `export_worker.py`, `preview_widget.py` |
| `cli.py` | Command-line entry point (`render`, `gui`, `devices`, `record`) |

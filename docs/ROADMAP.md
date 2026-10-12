# Roadmap

## Done

| Phase | Commit | Scope |
|---|---|---|
| 1 | `63f6a26` | CLI renderer: MIDI → falling notes (GPU, headless) → MP4 with synth audio |
| 2 | `bec5c94` | SoundFont piano audio, color modes (track / hand / pitch / auto), bloom glow |
| 3a | `dd3cd7c` | Live recording: USB MIDI + line-in audio, `record` / `devices` commands (tested with the real piano) |

Benchmarks (Intel UHD 620): Chopin Op. 10 No. 4 (2,187 notes, 1:52) at 1080p60 renders in ~190 s
without bloom; 720p30 with bloom + SoundFont renders at ~60 fps.

## Phase 3 — Desktop GUI and live MIDI input

Goal: open a MIDI file, preview it in real time, tweak the look, export; or connect a digital piano,
play live, record the performance as MIDI, and render it.

### Decisions

- **GUI toolkit: PySide6 (Qt).** Preview frames come from the existing `Renderer` (offscreen context,
  RGB readback) and are painted as a `QImage` at 720p — no GL context sharing with Qt. Export runs
  `cli.render()` in a `QThread` with its existing `progress` callback.
- **Live input: `python-rtmidi`** (same RtMidi library SeeMusic ships). Events go through a thread-safe
  queue; the GUI thread drains it once per frame.
- **Record, then render.** Live sessions are saved as `.mid` (via `mido`); the polished video comes
  from the normal offline pipeline, never from screen capture.
- **Hardware (confirmed):** the piano connects by **USB** (class-compliant MIDI, works directly with
  RtMidi), and its **real sound reaches the PC through an aux cable** into line-in. So a live session
  records **MIDI + the real piano audio together**, and the exported video uses the real recording
  instead of a SoundFont. No PC-side synth is needed for monitoring: the piano's own speakers or
  headphones are used while playing.

### Modules (one subagent each)

| # | Module | Owns | Depends on | Acceptance |
|---|---|---|---|---|
| 3.1 (done, hardware-tested) | `live/midi_input.py` | port listing, open/close, callback → queue of `(time, type, pitch, velocity)`, sustain CC64 | — | unit tests with a fake port; manual test lists the real piano |
| 3.2 (done, hardware-tested) | `live/recorder.py` | turn live events into a `Song` and save `.mid` with tempo 120 / 480 PPQ | 3.1 event format | round-trip test: record → save → `load_midi` gives same notes |
| 3.3 | `render/scene.py` (live mode) | `build_live_instances(active, released, t, …)`: held notes grow upward from the keys, released notes float up and fade | existing scene | geometry tests like `test_scene.py` |
| 3.4 (done, hardware-tested) | `live/audio_capture.py` + `--audio FILE` in CLI | record line-in (aux) to WAV with `sounddevice`, started on the same clock as MIDI capture; store the measured start offset so audio and notes line up; CLI/`render()` accept an existing audio file instead of synth/SoundFont | 3.1 clock | test with a fake input stream; manual check: a struck key's sound and its note hit the keyboard in the same frame (± 1 frame) |
| 3.5 | `preview/player.py` | playback clock (play / pause / seek), synced WAV playback, frame scheduling | scene, gl, audio | clock tests; no GUI imports |
| 3.6 | `gui/` | main window: open file, preview, transport bar, settings panel bound to `Preset`, export dialog, live tab (port picker, record button) | 3.1–3.5 | smoke test launches and closes the window offscreen (`QT_QPA_PLATFORM=offscreen`) |
| 3.7 | integration + docs | `look-music gui` entry point, README section, end-to-end manual test | all | full suite green; manual checklist below |

Order: 3.1, 3.3 and 3.5 in parallel → 3.2 and 3.4 → 3.6 → 3.7.
First step (usable before the GUI exists): 3.1 + 3.2 + 3.4 as a CLI command
`look-music record take.mid --audio take.wav`, then `look-music render take.mid --audio take.wav -o take.mp4`.

### Manual acceptance checklist

- [ ] Open the étude, play/pause/seek, preview stays in sync with audio
- [ ] Change color mode and bloom in the panel; preview updates immediately
- [ ] Export from the GUI matches `look-music render` output for the same preset
- [ ] Piano appears in the port list; key presses light keys and grow notes with no visible lag
- [ ] Record 30 s, stop, export → video matches what was played and carries the real piano audio
- [ ] Audio/visual sync: no audible offset between a note hitting the keys and its sound

### Risks

- **Line-in level and noise:** add an input meter in the live tab so the aux gain can be set before recording.
- **Clock drift:** MIDI timestamps (RtMidi) and audio frames (sound card) run on different clocks; over long
  takes, re-anchor using the audio sample count as the master clock.

## Later

- Particles at note onsets (GPU points + noise turbulence)
- Audio → MIDI with TransKun (`look-music transcribe song.wav`) — SeeMusic's AI feature
- Transparent-background export (ProRes 4444 / VP9 alpha) for overlays
- Note labels and a sheet-music strip (MusicXML)
- Keyboard detection on camera footage (OpenCV homography) to overlay notes on real performances

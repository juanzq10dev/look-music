"""Preview frame source: renders a song at any time with the GPU renderer."""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType
from typing import Any

from look_music.keyboard import key_layout
from look_music.midi import Song
from look_music.preset import Preset
from look_music.render.gl import Renderer
from look_music.render.scene import build_instances, prepare_notes


def _even(n: int) -> int:
    return max(2, n - n % 2)


class FrameSource:
    """Renders preview frames of a song at a given time with the GPU renderer."""

    def __init__(self, song: Song, preset: Preset, width: int = 1280, height: int = 720) -> None:
        self.song = song
        self.preset = preset
        self.width = _even(width)
        self.height = _even(height)
        self._notes = prepare_notes(song, preset)
        self._layout = key_layout(self.width)
        self._renderer: Renderer | None = None
        self._make_renderer()

    def _make_renderer(self) -> None:
        if self._renderer is not None:
            self._renderer.release()
            self._renderer = None
        self._renderer = Renderer(
            self.width, self.height, self.preset.background, bloom=self.preset.bloom_settings()
        )

    def frame(self, t: float) -> bytes:
        """RGB24 bytes, rows top-to-bottom, width*height*3 long."""
        instances = build_instances(
            self._notes, t, self.width, self.height, self._layout, self.preset
        )
        return self._renderer.render(instances)

    def live_frame(self, notes: Sequence[Any], t: float) -> bytes:
        """Like frame(), but for in-progress live notes (a LiveNote sequence)."""
        from look_music.render.scene import build_live_instances

        instances = build_live_instances(
            notes, t, self.width, self.height, self._layout, self.preset
        )
        return self._renderer.render(instances)

    def set_preset(self, preset: Preset) -> None:
        """Recompute note colors; recreate the renderer only if background or bloom changed."""
        rebuild = (
            preset.background != self.preset.background
            or preset.bloom_settings() != self.preset.bloom_settings()
        )
        self.preset = preset
        self._notes = prepare_notes(self.song, preset)
        if rebuild:
            self._make_renderer()

    def set_song(self, song: Song) -> None:
        self.song = song
        self._notes = prepare_notes(song, self.preset)

    def resize(self, width: int, height: int) -> None:
        self.width = _even(width)
        self.height = _even(height)
        self._layout = key_layout(self.width)
        self._make_renderer()

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.release()
            self._renderer = None

    def __enter__(self) -> FrameSource:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

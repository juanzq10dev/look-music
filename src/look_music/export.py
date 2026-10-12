"""Encode raw RGB24 frames into an H.264 MP4 by streaming them to ffmpeg."""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from pathlib import Path
from types import TracebackType

from imageio_ffmpeg import get_ffmpeg_exe

STDERR_TAIL_BYTES = 2000


class VideoWriter:
    """Context manager that writes RGB24 frames to an MP4, optionally with audio."""

    def __init__(
        self,
        path: str | Path,
        width: int,
        height: int,
        fps: int,
        audio_path: str | Path | None = None,
        crf: int = 18,
        preset: str = "fast",
    ) -> None:
        if width % 2 or height % 2:
            raise ValueError(f"width and height must be even, got {width}x{height}")
        self.width = width
        self.height = height
        self.frame_size = width * height * 3
        self.frames_written = 0

        cmd = [
            get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
            "-r", str(fps), "-i", "-",
        ]
        if audio_path is not None:
            cmd += ["-i", str(audio_path)]
        cmd += ["-map", "0:v"]
        if audio_path is not None:
            cmd += ["-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        cmd += [
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path),
        ]

        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        self._stderr_lines: deque[bytes] = deque(maxlen=200)
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self._closed = False

    def _drain_stderr(self) -> None:
        assert self._proc.stderr is not None
        for line in iter(self._proc.stderr.readline, b""):
            self._stderr_lines.append(line)

    def _stderr_tail(self) -> str:
        self._stderr_thread.join(timeout=2)
        data = b"".join(self._stderr_lines)[-STDERR_TAIL_BYTES:]
        return data.decode("utf-8", errors="replace").strip()

    def write(self, frame: bytes) -> None:
        """Append one frame: RGB24, rows top-to-bottom, exactly width*height*3 bytes."""
        if self._closed:
            raise RuntimeError("VideoWriter is closed")
        if len(frame) != self.frame_size:
            raise ValueError(
                f"frame must be {self.frame_size} bytes ({self.width}x{self.height} RGB24), "
                f"got {len(frame)}"
            )
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.write(frame)
        except OSError as exc:  # BrokenPipeError, or EINVAL on Windows
            raise RuntimeError(f"ffmpeg stopped accepting frames: {self._stderr_tail()}") from exc
        self.frames_written += 1

    def close(self) -> None:
        """Finish encoding; raise RuntimeError with ffmpeg's stderr tail on failure."""
        if self._closed:
            return
        self._closed = True
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.close()
        except OSError:
            pass  # ffmpeg already exited; the return code below reports why
        returncode = self._proc.wait()
        if returncode != 0:
            raise RuntimeError(f"ffmpeg exited with code {returncode}: {self._stderr_tail()}")
        self._stderr_thread.join(timeout=2)

    def _abort(self) -> None:
        self._closed = True
        self._proc.kill()
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
        except OSError:
            pass
        self._proc.wait()

    def __enter__(self) -> VideoWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            self.close()
        elif not self._closed:
            try:
                self._abort()
            except Exception:
                pass  # never mask the original exception
        return False

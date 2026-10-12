from __future__ import annotations

import numpy as np

from look_music.live.level_meter import LevelMeter


class Stream:
    def __init__(self, **kw):
        self.callback = kw["callback"]
        self.kw = kw
        self.started = self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


def test_level_follows_blocks_and_stops():
    streams = []

    def factory(**kw):
        streams.append(Stream(**kw))
        return streams[-1]

    m = LevelMeter(3, stream_factory=factory)
    m.start()
    m.start()  # idempotent
    assert len(streams) == 1 and streams[0].started and streams[0].kw["device"] == 3
    streams[0].callback(np.full((10, 2), -0.4, dtype=np.float32), 10, None, None)
    assert abs(m.level() - 0.4) < 1e-6
    m.stop()
    assert streams[0].closed and m.level() == 0.0
    m.stop()

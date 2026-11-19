"""Tests for ``ws_client.video.LatestFrameReader`` — no PyAV, no goggles.

The reader holds the trickiest logic in the app: the settle delay before a
restarted connect, wedge detection (goggles handing out connected-but-frameless
RTSP sessions), reconnect backoff, and latest-frame-only delivery. A fake ``av``
module is injected into ``sys.modules`` and ``video._open`` is monkeypatched, so
the state machine runs for real with no network or codec work.
"""
from __future__ import annotations

import sys
import time
import types

import numpy as np
import pytest


# ── fake av module (imported inside video.py functions) ────────────────────

class _FFmpegError(Exception):
    pass


@pytest.fixture(autouse=True)
def fake_av(monkeypatch):
    av = types.ModuleType("av")
    av.error = types.SimpleNamespace(FFmpegError=_FFmpegError)
    av.open = lambda *a, **k: (_ for _ in ()).throw(AssertionError(
        "_open must be monkeypatched by the test"))
    monkeypatch.setitem(sys.modules, "av", av)
    return av


from ws_client import video  # noqa: E402  (import after fixture definition is fine)


# ── fakes for what _open returns ────────────────────────────────────────────

class _FakeFrame:
    def to_ndarray(self, format):
        return np.zeros((2, 2, 3), dtype=np.uint8)


class _FakePacket:
    def __init__(self, frames):
        self._frames = frames

    def decode(self):
        return self._frames


class _FakeContainer:
    def __init__(self, packets):
        self._packets = packets
        self.closed = False

    def demux(self, stream):
        yield from self._packets

    def close(self):
        self.closed = True


def _wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)
    return True


# ── tests ────────────────────────────────────────────────────────────────────

def test_delivers_latest_frame(monkeypatch):
    monkeypatch.setattr(video, "_open",
                        lambda h, t: (_FakeContainer([_FakePacket([_FakeFrame()])]), None))
    r = video.LatestFrameReader("test-host").start()
    try:
        assert _wait_for(lambda: r.frames_decoded > 0)
        assert r.read() is not None
        assert r.read().shape == (2, 2, 3)
    finally:
        r.stop()


def test_start_delay_blocks_first_connect(monkeypatch):
    """A restarted reader must NOT touch the goggles during the settle window
    (the previous session is still being released)."""
    opened = []

    def _open(h, t):
        opened.append(time.monotonic())
        return _FakeContainer([_FakePacket([_FakeFrame()])]), None

    monkeypatch.setattr(video, "_open", _open)
    t0 = time.monotonic()
    r = video.LatestFrameReader("test-host", start_delay=0.4).start()
    try:
        assert _wait_for(lambda: opened)
        assert opened[0] - t0 >= 0.4, "connected before the settle delay elapsed"
    finally:
        r.stop()


def test_stop_during_start_delay_never_connects(monkeypatch):
    opened = []
    monkeypatch.setattr(video, "_open",
                        lambda h, t: opened.append(1) or (_FakeContainer([]), None))
    r = video.LatestFrameReader("test-host", start_delay=5.0).start()
    r.stop()
    assert not opened, "stop() during the settle delay must abort the connect"


def test_wedge_detection_after_empty_sessions(monkeypatch):
    """Goggles RTSP wedged: connects succeed but deliver zero frames. After
    WEDGE_THRESHOLD such sessions the reader must flag it (the UI tells the
    user to reboot the goggles) instead of hammering reconnects."""
    monkeypatch.setattr(video, "_open", lambda h, t: (_FakeContainer([]), None))
    r = video.LatestFrameReader("test-host").start()
    try:
        assert _wait_for(lambda: r.wedged)
        assert r.empty_sessions >= video.LatestFrameReader.WEDGE_THRESHOLD
        assert r.read() is None
    finally:
        r.stop()


def test_frames_reset_wedge_counter(monkeypatch):
    calls = {"n": 0}

    def _open(h, t):
        calls["n"] += 1
        if calls["n"] <= 2:
            return _FakeContainer([]), None          # two dead sessions
        return _FakeContainer([_FakePacket([_FakeFrame()])]), None

    monkeypatch.setattr(video, "_open", _open)
    r = video.LatestFrameReader("test-host").start()
    try:
        assert _wait_for(lambda: r.frames_decoded > 0)
        assert r.empty_sessions == 0, "a good session must clear the wedge count"
        assert not r.wedged
    finally:
        r.stop()


def test_connect_failure_sets_last_error_and_retries(monkeypatch):
    calls = {"n": 0}

    def _open(h, t):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("connection refused")
        return _FakeContainer([_FakePacket([_FakeFrame()])]), None

    monkeypatch.setattr(video, "_open", _open)
    r = video.LatestFrameReader("test-host").start()
    try:
        assert _wait_for(lambda: r.frames_decoded > 0)
        assert isinstance(r.last_error, OSError)
        assert calls["n"] >= 2, "must retry after a failed connect"
    finally:
        r.stop()


def test_corrupt_frames_are_skipped(monkeypatch):
    """UDP loss produces undecodable packets — they must be skipped, not fatal."""
    class _BadPacket:
        def decode(self):
            raise _FFmpegError("corrupt")

    packets = [_BadPacket(), _FakePacket([_FakeFrame()])]
    monkeypatch.setattr(video, "_open", lambda h, t: (_FakeContainer(packets), None))
    r = video.LatestFrameReader("test-host").start()
    try:
        assert _wait_for(lambda: r.frames_decoded > 0)
        assert isinstance(r.last_error, _FFmpegError)
    finally:
        r.stop()

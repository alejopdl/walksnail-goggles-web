"""Tests for the cross-platform single-instance lock (server._try_exclusive_lock).

The goggles serve a single RTSP session, so two ground stations targeting the
same host fight over it. This guard must reject a second instance. On Windows it
previously did NOTHING (the code bailed out when ``fcntl`` was missing); now it
locks via ``msvcrt`` there too. The POSIX path is exercised here; the Windows
branch is structurally identical.
"""
from __future__ import annotations

import os

from ws_client.web import server as srv


def test_second_handle_cannot_lock_same_file(tmp_path):
    p = tmp_path / "x.lock"
    fh1 = open(p, "a+")
    fh2 = open(p, "a+")
    try:
        assert srv._try_exclusive_lock(fh1) is True
        assert srv._try_exclusive_lock(fh2) is False  # already held by fh1
    finally:
        fh1.close()
        fh2.close()


def test_lock_frees_when_holder_closes(tmp_path):
    p = tmp_path / "x.lock"
    fh1 = open(p, "a+")
    assert srv._try_exclusive_lock(fh1) is True
    fh1.close()  # releasing the handle frees the lock
    fh2 = open(p, "a+")
    try:
        assert srv._try_exclusive_lock(fh2) is True
    finally:
        fh2.close()


def test_acquire_records_our_pid(monkeypatch, tmp_path):
    monkeypatch.setattr(srv.tempfile, "gettempdir", lambda: str(tmp_path))
    fh = srv._acquire_single_instance_lock("192.168.42.1")
    try:
        lockfiles = list(tmp_path.glob("ws-web-*.lock"))
        assert len(lockfiles) == 1
        assert lockfiles[0].read_text().strip() == str(os.getpid())
    finally:
        fh.close()

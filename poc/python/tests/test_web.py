"""Tests for the web ground station (no goggles required — all mocked)."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

# We need to mock goggles I/O before importing the server module,
# but FastAPI routes are already registered at import time. The approach:
# patch the module-level helpers that create WSClient / LatestFrameReader.

from ws_client.web import server as srv
from ws_client.client import DeviceInfo


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

FAKE_VERSION = {
    "nRetVal": 0,
    "stValue": {
        "Goggles_HW_Version": "4.0",
        "Goggles_SN": "AvatarX_079060",
        "Goggles_SW_Version": "39.44.15",
        "TX_SN": "AvatarMini_0965B4",
        "TX_HW_Version": "3.3",
        "TX_SW_Version": "39.44.15",
    },
}

FAKE_STATE = {
    "gas_type": 3, "vtx_connect": 1, "sky_prj_name": 0,
    "gas_rec_state": 0, "gas_voltage": 22.92, "delaytime": 36137,
    "gas_sd_space": 521, "sharemode": 0, "u8_mcs": 4, "distance": 0,
    "bitrate": 24206560, "vtx_rec_state": 0, "vtx_voltage": 4.16,
    "vtx_sd_space": 5, "vtx_tempeture": 41, "gas_tempeture": 49,
}

FAKE_RECORDS = {
    "nRetVal": 0,
    "total": 3,
    "rows": [
        {"szFileName": "AvatarG0001.mp4", "duration": 60},
        {"szFileName": "AvatarG0002.mp4", "duration": 120},
        {"szFileName": "AvatarG0003.mp4", "duration": 30},
    ],
}


def _make_fake_client():
    """Return a MagicMock that behaves like WSClient."""
    c = MagicMock()
    c.online.return_value = True
    c.get_version.return_value = DeviceInfo(
        goggles_sn="AvatarX_079060", goggles_hw="4.0", goggles_sw="39.44.15",
        tx_sn="AvatarMini_0965B4", tx_hw="3.3", tx_sw="39.44.15",
        raw=FAKE_VERSION["stValue"],
    )
    c.get_device_state.return_value = FAKE_STATE.copy()
    c.list_records.return_value = FAKE_RECORDS.copy()
    c.delete_record.return_value = None
    c.set_time.return_value = None
    c.record_url.side_effect = lambda f: f"http://192.168.42.1/record/{f}"
    type(c).rtsp_url = PropertyMock(return_value="rtsp://192.168.42.1/live.ch01")
    return c


def _make_fake_reader():
    """Return a MagicMock that behaves like LatestFrameReader."""
    r = MagicMock()
    # Return a small 4x4 black frame
    r.read.return_value = np.zeros((4, 4, 3), dtype=np.uint8)
    r.frames_decoded = 42
    r.last_error = None
    r.transport = "tcp"
    r._stop = MagicMock()
    r._stop.is_set.return_value = False
    r.start.return_value = r
    return r


@pytest.fixture(autouse=True)
def _mock_goggles():
    """Patch the server-module singletons so no network I/O happens."""
    fake_client = _make_fake_client()
    fake_reader = _make_fake_reader()

    srv._client = fake_client
    srv._reader = fake_reader
    srv._goggles_host = "127.0.0.1"
    srv._current_transport = "tcp"
    srv._stream_start_time = time.monotonic() - 100  # 100s of fake uptime
    srv._goggles_busy = 0
    srv._auto_shutdown_enabled = False
    srv._active_clients = 0

    yield fake_client, fake_reader

    # Reset
    srv._client = None
    srv._reader = None
    srv._goggles_busy = 0


@pytest.fixture
def client():
    """FastAPI TestClient."""
    return TestClient(srv.app)


# ═══════════════════════════════════════════════════════════════
#  API endpoint tests
# ═══════════════════════════════════════════════════════════════

class TestOnline:
    def test_returns_online_true(self, client):
        r = client.get("/api/online")
        assert r.status_code == 200
        assert r.json() == {"online": True}

    def test_returns_false_on_exception(self, client, _mock_goggles):
        fake_client, _ = _mock_goggles
        fake_client.online.side_effect = OSError("no route")
        r = client.get("/api/online")
        assert r.status_code == 200
        assert r.json() == {"online": False}


class TestInfo:
    def test_returns_device_info(self, client):
        r = client.get("/api/info")
        assert r.status_code == 200
        d = r.json()
        assert d["goggles_sn"] == "AvatarX_079060"
        assert d["goggles_sw"] == "39.44.15"
        assert d["tx_sn"] == "AvatarMini_0965B4"
        assert d["vtx_present"] is True

    def test_503_on_failure(self, client, _mock_goggles):
        fake_client, _ = _mock_goggles
        fake_client.get_version.side_effect = OSError("unreachable")
        r = client.get("/api/info")
        assert r.status_code == 503


class TestState:
    def test_returns_telemetry(self, client):
        r = client.get("/api/state")
        assert r.status_code == 200
        d = r.json()
        assert d["vtx_connect"] == 1
        assert d["gas_voltage"] == 22.92
        assert d["bitrate"] == 24206560

    def test_503_on_failure(self, client, _mock_goggles):
        fake_client, _ = _mock_goggles
        fake_client.get_device_state.side_effect = OSError("timeout")
        r = client.get("/api/state")
        assert r.status_code == 503


class TestSettime:
    def test_syncs_clock(self, client, _mock_goggles):
        fake_client, _ = _mock_goggles
        r = client.post("/api/settime")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        fake_client.set_time.assert_called_once()

    def test_500_on_failure(self, client, _mock_goggles):
        fake_client, _ = _mock_goggles
        fake_client.set_time.side_effect = RuntimeError("nRetVal=-1")
        r = client.post("/api/settime")
        assert r.status_code == 500


# ═══════════════════════════════════════════════════════════════
#  DVR endpoints
# ═══════════════════════════════════════════════════════════════

class TestRecords:
    def test_list_records(self, client):
        r = client.get("/api/records")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 3
        assert len(d["rows"]) == 3
        assert d["rows"][0]["szFileName"] == "AvatarG0001.mp4"

    def test_list_with_params(self, client, _mock_goggles):
        fake_client, _ = _mock_goggles
        client.get("/api/records?start=5&limit=10")
        # api_records runs the heavy query off the event loop with a generous
        # timeout (see server.api_records) — hence the timeout kwarg.
        fake_client.list_records.assert_called_with(5, 10, timeout=15.0)

    def test_503_on_failure(self, client, _mock_goggles):
        fake_client, _ = _mock_goggles
        fake_client.list_records.side_effect = OSError("unreachable")
        r = client.get("/api/records")
        assert r.status_code == 503


class TestDeleteRecord:
    def test_delete_ok(self, client, _mock_goggles):
        fake_client, _ = _mock_goggles
        r = client.delete("/api/records/AvatarG0001.mp4")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        fake_client.delete_record.assert_called_once_with("AvatarG0001.mp4")

    def test_500_on_failure(self, client, _mock_goggles):
        fake_client, _ = _mock_goggles
        fake_client.delete_record.side_effect = RuntimeError("delete failed")
        r = client.delete("/api/records/AvatarG0001.mp4")
        assert r.status_code == 500


class TestDownloadRecord:
    """The proxy-download route, with the inline (in-browser play) variant."""

    def _patch_urlopen(self, monkeypatch, payload=b"FAKEMP4DATA", headers=None):
        class _Resp:
            def __init__(self):
                self._sent = False
                self.headers = dict(headers or {})
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n):
                if self._sent:
                    return b""
                self._sent = True
                return payload
        monkeypatch.setattr(srv.urllib.request, "urlopen", lambda *a, **k: _Resp())

    def test_download_is_attachment_by_default(self, client, monkeypatch):
        self._patch_urlopen(monkeypatch)
        r = client.get("/api/records/AvatarG0001.mp4/download")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("video/mp4")
        assert r.headers["content-disposition"].startswith("attachment")
        assert "AvatarG0001.mp4" in r.headers["content-disposition"]
        assert r.content == b"FAKEMP4DATA"

    def test_inline_sets_inline_disposition(self, client, monkeypatch):
        self._patch_urlopen(monkeypatch)
        r = client.get("/api/records/AvatarG0001.mp4/download?inline=1")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("video/mp4")
        assert r.headers["content-disposition"].startswith("inline")
        assert "AvatarG0001.mp4" in r.headers["content-disposition"]

    def test_forwards_content_length(self, client, monkeypatch):
        """Browsers need the size to show real download progress."""
        self._patch_urlopen(monkeypatch, headers={"Content-Length": "11"})
        r = client.get("/api/records/AvatarG0001.mp4/download")
        assert r.status_code == 200
        assert r.headers["content-length"] == "11"

    def test_502_when_goggles_unreachable(self, client, monkeypatch):
        """The upstream is opened BEFORE streaming starts, so failure is a clean
        502 — not a 200 with a truncated body."""
        def _boom(*a, **k):
            raise OSError("no route to goggles")
        monkeypatch.setattr(srv.urllib.request, "urlopen", _boom)
        r = client.get("/api/records/AvatarG0001.mp4/download")
        assert r.status_code == 502

    def test_busy_flag_released_after_download(self, client, monkeypatch):
        """The goggles-busy counter must return to 0 once the transfer ends
        (telemetry polling stays paused only during the transfer)."""
        self._patch_urlopen(monkeypatch)
        assert not srv._busy()
        r = client.get("/api/records/AvatarG0001.mp4/download")
        assert r.content == b"FAKEMP4DATA"
        assert not srv._busy()

    def test_busy_flag_released_on_upstream_error(self, client, monkeypatch):
        def _boom(*a, **k):
            raise OSError("down")
        monkeypatch.setattr(srv.urllib.request, "urlopen", _boom)
        client.get("/api/records/AvatarG0001.mp4/download")
        assert not srv._busy()


# ═══════════════════════════════════════════════════════════════
#  Stream status & restart
# ═══════════════════════════════════════════════════════════════

class TestStreamStatus:
    def test_returns_status(self, client):
        r = client.get("/api/stream/status")
        assert r.status_code == 200
        d = r.json()
        assert d["running"] is True
        assert d["frames_decoded"] == 42
        assert d["transport"] == "tcp"
        assert d["uptime_s"] >= 99  # we set fake start 100s ago

    def test_no_reader(self, client, _mock_goggles):
        srv._reader = None
        r = client.get("/api/stream/status")
        d = r.json()
        assert d["running"] is False
        assert d["frames_decoded"] == 0

    def test_with_last_error(self, client, _mock_goggles):
        _, fake_reader = _mock_goggles
        fake_reader.last_error = ValueError("empty SDP")
        r = client.get("/api/stream/status")
        assert "empty SDP" in r.json()["last_error"]


class TestStreamRestart:
    def test_restart_tcp(self, client, _mock_goggles):
        _, fake_reader = _mock_goggles
        with patch.object(srv, 'LatestFrameReader') as MockLFR:
            new_reader = _make_fake_reader()
            MockLFR.return_value = new_reader
            r = client.post("/api/stream/restart?transport=tcp")
            assert r.status_code == 200
            assert r.json() == {"ok": True, "transport": "tcp"}
            fake_reader.stop.assert_called_once()

    def test_restart_udp(self, client, _mock_goggles):
        _, fake_reader = _mock_goggles
        with patch.object(srv, 'LatestFrameReader') as MockLFR:
            new_reader = _make_fake_reader()
            MockLFR.return_value = new_reader
            r = client.post("/api/stream/restart?transport=udp")
            assert r.json()["transport"] == "udp"

    def test_rejects_invalid_transport(self, client):
        r = client.post("/api/stream/restart?transport=quic")
        assert r.status_code == 422

    def test_restart_uses_settle_delay(self, client, _mock_goggles):
        """The regression v1.0.2 fixed: a restarted reader must wait 3 s so the
        goggles release their single RTSP session before we reconnect."""
        with patch.object(srv, 'LatestFrameReader') as MockLFR:
            MockLFR.return_value = _make_fake_reader()
            client.post("/api/stream/restart?transport=udp")
            _, kwargs = MockLFR.call_args
            assert kwargs["start_delay"] == 3.0
            assert kwargs["transport"] == "udp"


class TestConfig:
    def test_reports_goggles_host(self, client):
        """The SPA shows this in 'cannot reach <goggles>' messages — it must be
        the device address, not the web server's localhost."""
        r = client.get("/api/config")
        assert r.status_code == 200
        d = r.json()
        assert d["goggles_host"] == "127.0.0.1"
        assert d["rtsp_host"] == "127.0.0.1"  # falls back to goggles host

    def test_rtsp_host_override(self, client, _mock_goggles):
        srv._rtsp_host = "127.0.0.1:18554"
        try:
            assert client.get("/api/config").json()["rtsp_host"] == "127.0.0.1:18554"
        finally:
            srv._rtsp_host = ""


class TestReaderLifecycle:
    def test_same_transport_reuses_reader(self, _mock_goggles):
        """Multiple tabs / stream reconnects with the same transport must share
        one decoder thread, not restart the RTSP session."""
        _, fake_reader = _mock_goggles
        with patch.object(srv, 'LatestFrameReader') as MockLFR:
            got = srv._get_or_start_reader("tcp")  # matches _current_transport
            assert got is fake_reader
            MockLFR.assert_not_called()
            fake_reader.stop.assert_not_called()

    def test_transport_change_restarts_with_settle(self, _mock_goggles):
        _, fake_reader = _mock_goggles
        with patch.object(srv, 'LatestFrameReader') as MockLFR:
            MockLFR.return_value = _make_fake_reader()
            srv._get_or_start_reader("udp")
            fake_reader.stop.assert_called_once()
            _, kwargs = MockLFR.call_args
            assert kwargs["start_delay"] == 3.0
        srv._reader = None

    def test_first_start_has_no_settle_delay(self, _mock_goggles):
        """Cold start must connect immediately — the delay is only for restarts."""
        srv._reader = None
        with patch.object(srv, 'LatestFrameReader') as MockLFR:
            MockLFR.return_value = _make_fake_reader()
            srv._get_or_start_reader("tcp")
            _, kwargs = MockLFR.call_args
            assert kwargs["start_delay"] == 0.0
        srv._reader = None


# ═══════════════════════════════════════════════════════════════
#  Auto-shutdown (packaged app quits when the last tab closes)
# ═══════════════════════════════════════════════════════════════

class TestAutoShutdown:
    def test_shutdown_endpoint_schedules_quit(self, client, monkeypatch):
        called = threading.Event()
        monkeypatch.setattr(srv, "_quit_process", called.set)
        r = client.post("/api/shutdown")
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert called.wait(2.0), "quit must fire shortly after the reply"

    def test_no_autoshutdown_when_disabled(self, monkeypatch):
        """ws-web CLI mode: closing the tab must NOT kill the server."""
        called = []
        monkeypatch.setattr(srv, "_quit_process", lambda: called.append(1))
        srv._auto_shutdown_enabled = False
        srv._active_clients = 0
        srv._do_autoshutdown()
        assert not called

    def test_autoshutdown_when_no_clients(self, monkeypatch):
        called = []
        monkeypatch.setattr(srv, "_quit_process", lambda: called.append(1))
        srv._auto_shutdown_enabled = True
        srv._active_clients = 0
        srv._do_autoshutdown()
        assert called

    def test_autoshutdown_cancelled_by_reconnect(self, monkeypatch):
        """A tab reload reconnects within the grace period — must not quit."""
        called = []
        monkeypatch.setattr(srv, "_quit_process", lambda: called.append(1))
        srv._auto_shutdown_enabled = True
        srv._active_clients = 1   # client came back before the timer fired
        srv._do_autoshutdown()
        assert not called

    def test_ws_client_count_tracks_connections(self, client):
        assert srv._active_clients == 0
        with client.websocket_connect("/ws/telemetry") as ws:
            ws.receive_json()
            assert srv._active_clients == 1
        # After disconnect the count returns to zero (allow a beat for teardown)
        deadline = time.monotonic() + 2.0
        while srv._active_clients != 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert srv._active_clients == 0


# ═══════════════════════════════════════════════════════════════
#  MJPEG stream
# ═══════════════════════════════════════════════════════════════

class TestMJPEGStream:
    """MJPEG streaming tests.

    NOTE: Starlette's TestClient runs the ASGI app synchronously, so
    iter_raw/iter_bytes on an infinite async generator hangs. We test
    the endpoint validation (params, headers) synchronously and test the
    async generator directly via asyncio.
    """

    def test_stream_rejects_invalid_transport(self, client):
        r = client.get("/video/stream?transport=invalid")
        assert r.status_code == 422

    def test_stream_rejects_bad_quality(self, client):
        r = client.get("/video/stream?quality=200")
        assert r.status_code == 422

    def test_stream_rejects_bad_scale(self, client):
        r = client.get("/video/stream?scale=5.0")
        assert r.status_code == 422

    def test_mjpeg_gen_yields_jpeg_frames(self, _mock_goggles):
        """Directly test the async generator produces valid MJPEG boundary+JPEG."""
        import asyncio

        _, fake_reader = _mock_goggles
        # 4x4 black frame
        fake_reader.read.return_value = np.zeros((4, 4, 3), dtype=np.uint8)

        async def _collect():
            chunks = []
            gen = srv._mjpeg_gen(fake_reader, quality=50, scale=1.0, fps=60)
            async for chunk in gen:
                chunks.append(chunk)
                if len(chunks) >= 3:
                    break
            return chunks

        chunks = asyncio.run(_collect())
        assert len(chunks) == 3
        for chunk in chunks:
            assert chunk.startswith(b"--frame\r\n")
            assert b"Content-Type: image/jpeg" in chunk
            assert b"\xff\xd8\xff" in chunk  # JPEG magic

    def test_mjpeg_gen_placeholder_on_none(self, _mock_goggles):
        """When reader.read() returns None, generator yields a placeholder JPEG."""
        import asyncio

        _, fake_reader = _mock_goggles
        fake_reader.read.return_value = None
        fake_reader.last_error = None

        async def _collect():
            gen = srv._mjpeg_gen(fake_reader, quality=50, scale=1.0, fps=60)
            async for chunk in gen:
                return chunk  # just get the first one

        chunk = asyncio.run(_collect())
        assert chunk.startswith(b"--frame\r\n")
        assert b"\xff\xd8\xff" in chunk

    def test_mjpeg_gen_placeholder_with_error(self, _mock_goggles):
        """Placeholder includes error context when reader has an error."""
        import asyncio

        _, fake_reader = _mock_goggles
        fake_reader.read.return_value = None
        fake_reader.last_error = RuntimeError("empty SDP response")

        async def _collect():
            gen = srv._mjpeg_gen(fake_reader, quality=50, scale=1.0, fps=60)
            async for chunk in gen:
                return chunk

        chunk = asyncio.run(_collect())
        assert b"\xff\xd8\xff" in chunk  # still a valid JPEG


# ═══════════════════════════════════════════════════════════════
#  WebSocket telemetry
# ═══════════════════════════════════════════════════════════════

class TestWebSocketTelemetry:
    def test_receives_state_message(self, client):
        with client.websocket_connect("/ws/telemetry") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "state"
            assert msg["data"]["vtx_connect"] == 1
            assert msg["data"]["gas_voltage"] == 22.92

    def test_receives_error_on_failure(self, client, _mock_goggles):
        fake_client, _ = _mock_goggles
        fake_client.get_device_state.side_effect = OSError("connection refused")
        with client.websocket_connect("/ws/telemetry") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "connection refused" in msg["message"]


# ═══════════════════════════════════════════════════════════════
#  Static file serving
# ═══════════════════════════════════════════════════════════════

class TestStaticServing:
    def test_index_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "WS WiFi Stream" in r.text

    def test_index_contains_key_elements(self, client):
        r = client.get("/")
        html = r.text
        # Key UI elements present
        assert 'id="stream-img"' in html
        assert 'id="osd"' in html
        assert '/video/stream' in html
        assert '/ws/telemetry' in html
        assert 'settings-drawer' in html

    def test_index_contains_media_and_tooltips(self, client):
        """The media library, REC status, tooltip system and settings
        hardening must be wired into the served SPA."""
        html = client.get("/").text
        # Media library
        assert 'id="media-overlay"' in html
        assert 'function openMedia(' in html
        assert 'inline=1' in html              # in-browser play uses the inline route
        # Recording status card (status-only — no remote start/stop)
        assert 'id="rec-state-g"' in html
        assert 'id="rec-state-v"' in html
        # Custom tooltip system + annotations
        assert 'id="tooltip"' in html
        assert 'function initTooltips(' in html
        assert html.count('data-tip') > 30     # tooltips on most info surfaces
        # Settings drawer hardening
        assert 'id="settings-backdrop"' in html
        assert 'function closeSettings(' in html

    def test_index_transport_switch_releases_session_up_front(self, client):
        """The settle countdown must be truthful: the frontend releases the
        goggles RTSP session at t=0 via the restart endpoint (backend settles in
        parallel), instead of holding it for the whole countdown."""
        html = client.get("/").text
        assert '/api/stream/restart' in html
        assert 'function startStreamWithSettle(' in html
        # Goggles address comes from the server config, not location.hostname
        assert '/api/config' in html


# ═══════════════════════════════════════════════════════════════
#  Helpers (internal)
# ═══════════════════════════════════════════════════════════════

class TestHelpers:
    def test_encode_frame_full_size(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        jpeg = srv._encode_frame(frame, quality=80, scale=1.0)
        assert len(jpeg) > 100
        assert jpeg[:3] == b"\xff\xd8\xff"  # JPEG magic

    def test_encode_frame_scaled(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        full = srv._encode_frame(frame, quality=80, scale=1.0)
        half = srv._encode_frame(frame, quality=80, scale=0.5)
        # Scaled-down should be smaller
        assert len(half) < len(full)

    def test_make_placeholder_cached(self):
        p1 = srv._make_placeholder("Test", "sub", 50, 320, 180)
        p2 = srv._make_placeholder("Test", "sub", 50, 320, 180)
        assert p1 is p2  # same object (cached)
        assert p1[:3] == b"\xff\xd8\xff"

    def test_make_placeholder_different_msg_not_cached(self):
        p1 = srv._make_placeholder("A", "", 50, 320, 180)
        p2 = srv._make_placeholder("B", "", 50, 320, 180)
        assert p1 is not p2

    def test_get_or_start_reader_transport_switch(self):
        """Switching transport stops the old reader and creates a new one."""
        with patch.object(srv, 'LatestFrameReader') as MockLFR:
            new_reader = _make_fake_reader()
            MockLFR.return_value = new_reader

            old = srv._reader
            srv._get_or_start_reader("udp")
            # Old reader should be stopped
            if old:
                old.stop.assert_called()
            assert srv._current_transport == "udp"
            # Restore
            srv._reader = None

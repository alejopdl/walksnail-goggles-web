"""Tests for the keep-alive control-plane transport (``ws_client.client``).

No goggles required — a tiny local HTTP server stands in for the device. These
cover the fix for the "status flapping online/offline" bug: the client must
reuse ONE TCP connection across polls (not open a fresh one every 500 ms, which
floods the goggles' embedded server and — on Windows — piles up TIME_WAIT
sockets until polls fail in bursts), and it must recover transparently when a
kept-alive socket goes stale.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ws_client.client import WSClient
from ws_client.protocol import GogglesError


# ── A configurable stand-in for the goggles' HTTP server ──────────────────
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # enables keep-alive so we can prove reuse

    def do_POST(self):
        cfg = self.server.cfg
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        cfg["requests"] += 1
        if cfg.get("delay"):
            time.sleep(cfg["delay"])  # simulate a slow device (timeout tests)
        body = cfg["body"]
        if isinstance(body, str):
            body = body.encode()
        self.send_response(cfg.get("status", 200))
        self.send_header("Content-Length", str(len(body)))
        if cfg.get("force_close"):        # simulate a server that won't keep-alive
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep test output clean
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, cfg):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.cfg = cfg
        self.conns = 0  # count of accepted TCP connections (NOT requests)

    def get_request(self):
        req = super().get_request()
        self.conns += 1
        return req


@pytest.fixture
def server():
    cfg = {"requests": 0, "body": b'{"nRetVal":0,"stValue":{"ok":1}}'}
    srv = _Server(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _client(server, **kw):
    host, port = server.server_address
    return WSClient(f"{host}:{port}", **kw)


# ── host/port parsing ─────────────────────────────────────────────────────
def test_host_port_default_is_80():
    assert WSClient("192.168.42.1")._host_port() == ("192.168.42.1", 80)


def test_host_port_explicit_port():
    assert WSClient("127.0.0.1:18080")._host_port() == ("127.0.0.1", 18080)


# ── the core fix: one connection, reused ──────────────────────────────────
def test_polls_reuse_a_single_connection(server):
    c = _client(server, timeout=2.0)
    for _ in range(15):
        assert c._request("/ajaxcom", b"x=1", 2.0) == server.cfg["body"]
    assert server.cfg["requests"] == 15
    assert server.conns == 1, "15 polls must ride ONE connection, not open 15"


def test_concurrent_callers_share_one_connection(server):
    """Multiple threads (≈ multiple browser tabs) must still use one socket."""
    c = _client(server, timeout=2.0)
    errors: list[Exception] = []

    def worker():
        try:
            for _ in range(10):
                c._request("/ajaxcom", b"x=1", 2.0)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert server.cfg["requests"] == 40
    assert server.conns == 1, "the lock must serialise callers onto one connection"


# ── resilience: reconnect on stale / closed sockets ───────────────────────
def test_reconnects_after_stale_socket(server):
    c = _client(server, timeout=2.0)
    c._request("/ajaxcom", b"x=1", 2.0)
    assert server.conns == 1
    # Simulate the kept-alive socket dying under us (idle timeout, AP blip).
    c._conn.sock.close()
    # The next poll must transparently reconnect, not raise.
    assert c._request("/ajaxcom", b"x=1", 2.0) == server.cfg["body"]
    assert server.conns == 2


def test_server_without_keepalive_reconnects_each_call(server):
    server.cfg["force_close"] = True  # server sends 'Connection: close'
    c = _client(server, timeout=2.0)
    for _ in range(3):
        c._request("/ajaxcom", b"x=1", 2.0)
    assert server.conns == 3  # honoured the close; no worse than the old behaviour


# ── failure modes ─────────────────────────────────────────────────────────
def test_unreachable_goggles_raise_quickly_without_retry_loop():
    c = WSClient("127.0.0.1:1", timeout=1.0)  # nothing listening → refused
    t0 = time.monotonic()
    with pytest.raises(Exception):
        c._request("/ajaxcom", b"x=1", 1.0)
    assert time.monotonic() - t0 < 3.0, "must not hang or retry forever"
    assert c._conn is None


def test_per_call_timeout_is_applied(server):
    server.cfg["delay"] = 1.0  # device takes 1 s to answer
    c = _client(server, timeout=5.0)
    t0 = time.monotonic()
    with pytest.raises(Exception):
        c._request("/ajaxcom", b"x=1", 0.3)  # this call only allows 0.3 s
    assert time.monotonic() - t0 < 0.9
    assert c._conn is None  # dropped after the timeout


def test_http_error_status_raises(server):
    server.cfg["status"] = 500
    server.cfg["body"] = b"kaboom"
    c = _client(server, timeout=2.0)
    with pytest.raises(http.client.HTTPException):
        c._request("/ajaxcom", b"x=1", 2.0)
    assert c._conn is None


# ── end-to-end through _post + parse_response ─────────────────────────────
def test_get_device_state_parses_stvalue(server):
    server.cfg["body"] = json.dumps(
        {"nRetVal": 0, "stValue": {"vtx_connect": 1, "gas_voltage": 22.9}}
    ).encode()
    c = _client(server, timeout=2.0)
    assert c.get_device_state(timeout=2.0) == {"vtx_connect": 1, "gas_voltage": 22.9}


def test_error_payload_raises_goggles_error(server):
    server.cfg["body"] = json.dumps({"nRetVal": -1, "szError": "boom"}).encode()
    c = _client(server, timeout=2.0)
    with pytest.raises(GogglesError):
        c.get_version()

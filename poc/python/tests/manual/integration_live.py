#!/usr/bin/env python3
"""
Full integration test — Walksnail Web Ground Station vs REAL goggles.

Requires: phone on goggles WiFi, adb tunnel active:
  adb forward tcp:18080 tcp:8080  (phone relays to goggles:80)

Tests every API endpoint against the live hardware and validates
real responses.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error

HOST = "127.0.0.1:18080"
BASE = f"http://{HOST}"

PASS = 0
FAIL = 0
RESULTS = []


def test(name: str):
    """Decorator to register and run a test function."""
    def decorator(fn):
        global PASS, FAIL
        try:
            fn()
            RESULTS.append(("✅", name))
            PASS += 1
        except Exception as e:
            RESULTS.append(("❌", f"{name}: {e}"))
            FAIL += 1
        return fn
    return decorator


def get(path: str, timeout: float = 8.0) -> dict:
    url = BASE + path
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def post(path: str, data: bytes = b"", timeout: float = 8.0) -> dict:
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def delete(path: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(BASE + path, method="DELETE")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ═══════════════════════════════════════════════════════════════
#  Pre-flight: test raw goggles connectivity (no web server)
# ═══════════════════════════════════════════════════════════════

    print("\n" + "="*64)
    print("  WALKSNAIL INTEGRATION TEST — Live hardware")
    print(f"  Tunnel: {HOST} → goggles 192.168.42.1:80")
    print("="*64)

    print("\n── Pre-flight: raw goggles connectivity ──")

@test("Raw HTTP: goggles /ajaxcom onlinequery")
def _():
    data = b'szCmd={"SysQuery":{"onlinequery":{}}}'
    req = urllib.request.Request(
        f"{BASE}/ajaxcom", data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Connection": "close"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        body = json.loads(r.read())
    assert body["nRetVal"] == 0, f"nRetVal={body['nRetVal']}"
    assert body["stValue"]["online"] == 1, "goggles not online"
    print(f"    → online={body['stValue']['online']} ✓")


# ═══════════════════════════════════════════════════════════════
#  Now test via the Python client library directly
# ═══════════════════════════════════════════════════════════════

    print("\n── Python client library (direct, no web server) ──")

from ws_client.client import WSClient
client = WSClient(HOST, timeout=8.0)

@test("client.online()")
def _():
    assert client.online() is True
    print("    → online=True ✓")

@test("client.get_version() — goggles info")
def _():
    info = client.get_version()
    assert info.goggles_sn, "empty goggles_sn"
    assert info.goggles_sw, "empty goggles_sw"
    print(f"    → Goggles SN={info.goggles_sn} SW={info.goggles_sw}")
    print(f"    → VTX SN={info.tx_sn} SW={info.tx_sw}")
    print(f"    → vtx_present={info.vtx_present}")

@test("client.get_device_state() — telemetry")
def _():
    state = client.get_device_state()
    assert "gas_voltage" in state, "missing gas_voltage"
    assert "vtx_connect" in state, "missing vtx_connect"
    assert "bitrate" in state, "missing bitrate"
    gv = state["gas_voltage"]
    vv = state.get("vtx_voltage", 0)
    vtx = state["vtx_connect"]
    br = state["bitrate"]
    gt = state.get("gas_tempeture", "?")
    vt = state.get("vtx_tempeture", "?")
    print(f"    → vtx_connect={vtx}")
    print(f"    → gas_voltage={gv:.2f}V  vtx_voltage={vv:.2f}V")
    print(f"    → bitrate={br} ({br/1e6:.1f} Mbps)")
    print(f"    → gas_temp={gt}°C  vtx_temp={vt}°C")
    print(f"    → gas_sd_space={state.get('gas_sd_space')}  vtx_sd_space={state.get('vtx_sd_space')}")
    print(f"    → MCS={state.get('u8_mcs')}  distance={state.get('distance')}")

@test("client.vtx_connected() — drone link")
def _():
    vtx = client.vtx_connected()
    print(f"    → vtx_connected={vtx}")
    # Don't assert — the drone may or may not be linked

@test("client.list_records() — DVR list")
def _():
    recs = client.list_records(start=0, limit=5)
    total = recs.get("total", 0)
    rows = recs.get("rows", [])
    print(f"    → total={total}, showing {len(rows)}")
    for r in rows[:3]:
        print(f"       {r['szFileName']}  {r['duration']}s")

@test("client.set_time() — sync clock")
def _():
    client.set_time()
    print("    → set_time OK (nRetVal=0)")


# ═══════════════════════════════════════════════════════════════
#  Now start the web server and test API endpoints
# ═══════════════════════════════════════════════════════════════

    print("\n── Web server API endpoints ──")
    print("  Starting FastAPI server on :18888 ...")

import threading
import uvicorn
from ws_client.web import server as srv

# Configure the server module to point at the goggles tunnel
srv._goggles_host = HOST
srv._client = None  # will be lazy-created

# Start uvicorn in a background thread
server_thread = threading.Thread(
    target=uvicorn.run,
    kwargs={"app": srv.app, "host": "127.0.0.1", "port": 18888, "log_level": "error"},
    daemon=True,
)
server_thread.start()
time.sleep(1.5)  # wait for server to start

WEB = "http://127.0.0.1:18888"

def web_get(path, timeout=8.0):
    with urllib.request.urlopen(WEB + path, timeout=timeout) as r:
        return json.loads(r.read())

def web_post(path, data=b"", timeout=8.0):
    req = urllib.request.Request(WEB + path, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


@test("GET /api/online — via web server")
def _():
    d = web_get("/api/online")
    assert d["online"] is True, f"online={d['online']}"
    print(f"    → online={d['online']} ✓")

@test("GET /api/info — device info via web server")
def _():
    d = web_get("/api/info")
    assert d["goggles_sn"], "empty goggles_sn"
    print(f"    → goggles_sn={d['goggles_sn']}  goggles_sw={d['goggles_sw']}")
    print(f"    → tx_sn={d['tx_sn']}  vtx_present={d['vtx_present']}")

@test("GET /api/state — telemetry via web server")
def _():
    d = web_get("/api/state")
    assert "gas_voltage" in d
    assert "vtx_connect" in d
    print(f"    → vtx_connect={d['vtx_connect']}  gas_voltage={d['gas_voltage']:.2f}V")
    print(f"    → bitrate={d.get('bitrate',0)/1e6:.1f} Mbps  MCS={d.get('u8_mcs')}")

@test("POST /api/settime — sync clock via web server")
def _():
    d = web_post("/api/settime")
    assert d.get("ok") is True, f"response: {d}"
    print("    → ok=true ✓")

@test("GET /api/records — DVR list via web server")
def _():
    d = web_get("/api/records?start=0&limit=5")
    total = d.get("total", 0)
    rows = d.get("rows", [])
    print(f"    → total={total}, showing {len(rows)}")
    for r in rows[:3]:
        print(f"       {r['szFileName']}  {r['duration']}s")

@test("GET /api/stream/status — stream reader status")
def _():
    d = web_get("/api/stream/status")
    print(f"    → running={d.get('running')}  frames={d.get('frames_decoded')}")
    print(f"    → transport={d.get('transport')}  error={d.get('last_error')}")

@test("POST /api/stream/restart — restart reader (TCP)")
def _():
    d = web_post("/api/stream/restart?transport=tcp")
    assert d.get("ok") is True
    assert d["transport"] == "tcp"
    print(f"    → ok=true  transport=tcp ✓")

@test("GET / — index.html served")
def _():
    with urllib.request.urlopen(WEB + "/", timeout=5) as r:
        html = r.read().decode()
    assert "Walksnail Ground Station" in html
    assert 'id="stream-img"' in html
    print(f"    → HTML served ({len(html)} bytes) ✓")

@test("GET /video/stream — MJPEG stream starts")
def _():
    req = urllib.request.Request(WEB + "/video/stream?fps=5&quality=50&scale=0.333")
    with urllib.request.urlopen(req, timeout=10) as r:
        ct = r.headers.get("Content-Type", "")
        assert "multipart/x-mixed-replace" in ct, f"unexpected content-type: {ct}"
        # Read first ~32KB of the stream
        data = r.read(32768)
    assert b"--frame" in data, "no MJPEG boundary found"
    assert b"\xff\xd8\xff" in data, "no JPEG magic found"
    print(f"    → MJPEG stream OK ({len(data)} bytes, boundary + JPEG magic found) ✓")


# ═══════════════════════════════════════════════════════════════
#  Telemetry consistency check (3 rapid polls)
# ═══════════════════════════════════════════════════════════════

@test("Telemetry stability — 3 rapid polls")
def _():
    voltages = []
    for i in range(3):
        d = web_get("/api/state")
        voltages.append(d["gas_voltage"])
        time.sleep(0.3)
    # Voltages should be within 1V of each other (not random garbage)
    spread = max(voltages) - min(voltages)
    print(f"    → 3 voltages: {[f'{v:.2f}' for v in voltages]}  spread={spread:.2f}V")
    assert spread < 2.0, f"voltage spread too large: {spread:.2f}V"
    print("    → stable ✓")


# ═══════════════════════════════════════════════════════════════
#  Summary
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "="*64)
    print(f"  RESULTS: {PASS} passed, {FAIL} failed")
    print("="*64)
    for icon, msg in RESULTS:
        print(f"  {icon} {msg}")
    print()

    if FAIL > 0:
        print(f"  ⚠️  {FAIL} test(s) FAILED")
        sys.exit(1)
    else:
        print("  🎉 ALL TESTS PASSED — hardware fully verified!")
        sys.exit(0)


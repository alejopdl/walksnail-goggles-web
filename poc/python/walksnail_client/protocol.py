"""Walksnail Goggles X protocol primitives.

Reverse-engineered (interoperability research) — see ../../PROTOCOL_SPEC.md.
This module is pure: it builds request payloads and parses responses. No I/O,
no decompiled code — just the wire format learned from observing the protocol.

Wire summary
------------
Two HTTP command channels on the goggles AP (host 192.168.42.1, port 80). Both
take a form-encoded body ``szCmd=<JSON>`` and reply with JSON ``{"nRetVal": 0,
...}`` (0 = ok; non-zero = error; ``-100`` seen when a command hits the wrong
endpoint).

* ``POST /ajaxcom``   -> system query/control: ``{"SysQuery": {...}}`` / ``{"SysCtrl": {...}}``
* ``POST /querydata`` -> DVR records:          ``{"query_record": {...}}`` etc.

Live video is plain H.264-over-RTSP at ``rtsp://<host>/live.ch01``.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

DEFAULT_HOST = "192.168.42.1"

# Endpoints (paths under http://<host>)
EP_AJAXCOM = "/ajaxcom"
EP_QUERYDATA = "/querydata"

RTSP_PATH = "/live.ch01"


def rtsp_url(host: str = DEFAULT_HOST) -> str:
    """Live video stream URL (H.264 High@4.0, 1920x1080@60 when a VTX is linked)."""
    return f"rtsp://{host}{RTSP_PATH}"


def record_url(filename: str, host: str = DEFAULT_HOST) -> str:
    """Download URL for a DVR clip returned by :func:`query_record`."""
    return f"http://{host}/record/{filename}"


def szcmd(obj: dict[str, Any]) -> str:
    """Encode a command object as the ``szCmd`` form value the goggles expect.

    Uses compact separators to mirror the app's payloads.
    """
    return "szCmd=" + json.dumps(obj, separators=(",", ":"))


# --- /ajaxcom command builders (SysQuery / SysCtrl) -----------------------

def sys_query(name: str, arg: Any = None) -> dict[str, Any]:
    """Build a ``{"SysQuery": {name: arg}}`` command body object."""
    return {"SysQuery": {name: ({} if arg is None else arg)}}


def sys_ctrl(name: str, arg: Any = None) -> dict[str, Any]:
    """Build a ``{"SysCtrl": {name: arg}}`` command body object."""
    return {"SysCtrl": {name: ({} if arg is None else arg)}}


CMD_VERSION = sys_query("version")
CMD_ONLINE = sys_query("onlinequery")
CMD_DEVICE_STATE = sys_query("devicestate", 0)
CMD_REBOOT = sys_ctrl("reboot")
CMD_UPDATE_REBOOT = sys_ctrl("updatereboot")
CMD_FACTORY_DEFAULT = sys_ctrl("default")
CMD_FORMAT_GOGGLES_SD = sys_ctrl("gassdcardformat")
CMD_FORMAT_VTX_SD = sys_ctrl("vtxsdcardformat")


def cmd_delete_record(filename: str) -> dict[str, Any]:
    """``SysCtrl/deletegasrecord`` for one DVR file (by ``szFileName``)."""
    return sys_ctrl("deletegasrecord", {"szFileName": filename})


def cmd_set_time(when: _dt.datetime | None = None) -> dict[str, Any]:
    """``SysCtrl/settime`` body for the given (or current local) time."""
    t = when or _dt.datetime.now()
    return sys_ctrl("settime", {
        "dwYear": t.year, "byMonth": t.month, "byDay": t.day,
        "byHour": t.hour, "byMinute": t.minute, "bySecond": t.second,
    })


# --- /querydata command builders ------------------------------------------

def cmd_query_record(start: int = 0, limit: int = 1_215_752_191) -> dict[str, Any]:
    """List DVR records. Default ``limit`` matches the app's "all" value."""
    return {"query_record": {"start": start, "limit": limit}}


# --- response parsing ------------------------------------------------------

class GogglesError(RuntimeError):
    """A command returned a non-zero ``nRetVal``."""

    def __init__(self, ret: int, msg: str = "", *, command: str = ""):
        self.ret = ret
        self.msg = msg
        self.command = command
        detail = f" ({msg})" if msg else ""
        where = f" for {command}" if command else ""
        super().__init__(f"goggles returned nRetVal={ret}{detail}{where}")


def parse_response(raw: bytes | str, *, command: str = "") -> dict[str, Any]:
    """Parse a goggles JSON reply, raising :class:`GogglesError` on failure.

    Returns the full decoded dict (callers pick ``stValue`` / ``rows`` etc.).
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    data = json.loads(raw)
    ret = data.get("nRetVal", 0)
    if ret != 0:
        raise GogglesError(ret, data.get("szError", ""), command=command)
    return data

"""Control-plane client for the FPV goggles.

Pure stdlib (urllib) so it runs anywhere with no dependencies. The device must
be reachable on its Wi-Fi AP (default host 192.168.42.1).
"""

from __future__ import annotations

import http.client
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import debuglog
from . import protocol as p


@dataclass
class DeviceInfo:
    goggles_sn: str
    goggles_hw: str
    goggles_sw: str
    tx_sn: str
    tx_hw: str
    tx_sw: str
    raw: dict[str, Any]

    @property
    def vtx_present(self) -> bool:
        """Heuristic: a linked air unit reports a real serial (not dashes)."""
        return bool(self.tx_sn) and set(self.tx_sn) != {"-"}


class WSClient:
    """Synchronous HTTP control client.

    >>> c = WSClient()
    >>> c.get_version().goggles_sw
    '39.44.15'
    """

    def __init__(self, host: str = p.DEFAULT_HOST, *, timeout: float = 5.0):
        self.host = host
        self.timeout = timeout
        self.base = f"http://{host}"
        # A single kept-alive HTTP connection, reused across control calls. The
        # goggles run a tiny embedded HTTP server; opening a fresh TCP connection
        # for every poll (twice a second) floods it with connect/teardown churn —
        # tolerable on macOS but on Windows the closed sockets pile up in
        # TIME_WAIT and polls start failing in bursts, which the UI shows as the
        # status flapping online/offline while the (single, persistent) RTSP
        # video keeps flowing. Reusing one connection removes that churn.
        self._conn: http.client.HTTPConnection | None = None
        self._conn_lock = threading.Lock()

    # --- transport --------------------------------------------------------

    def _host_port(self) -> tuple[str, int]:
        """Split ``host`` (``"1.2.3.4"`` or ``"127.0.0.1:18080"``) into host+port."""
        if ":" in self.host:
            h, port = self.host.rsplit(":", 1)
            return h, int(port)
        return self.host, 80

    def _close_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def _send(self, endpoint: str, data: bytes, timeout: float) -> bytes:
        """One request over the (possibly reused) kept-alive connection."""
        conn = self._conn
        if conn is None:
            host, port = self._host_port()
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
            self._conn = conn
        # Apply this call's timeout even to an already-open socket (records use a
        # much longer timeout than the 2s telemetry poll on the same connection).
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        conn.request("POST", endpoint, body=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
        })
        resp = conn.getresponse()
        raw = resp.read()  # must drain fully for the connection to be reusable
        status = resp.status
        if resp.will_close:  # server won't keep-alive — drop so next call reconnects
            self._close_conn()
        if status >= 400:
            # Match the old urllib.urlopen behaviour: an HTTP error is a failure,
            # not a body to parse. Drop the connection so we don't reuse it.
            self._close_conn()
            raise http.client.HTTPException(f"HTTP {status} {resp.reason}")
        return raw

    def _request(self, endpoint: str, data: bytes, timeout: float,
                 *, retry_stale: bool = True) -> bytes:
        """Send a POST, transparently reconnecting once if a reused socket was stale.

        Serialised by ``_conn_lock`` so concurrent callers (multiple browser tabs,
        telemetry + a records query) share the one connection instead of each
        opening their own — which would reintroduce the churn we're avoiding.

        ``retry_stale=False`` disables the reconnect-and-resend: if the first
        request reached the goggles but the response was lost, a resend would
        execute the command twice. Mutating commands (SysCtrl) must not risk that.
        """
        with self._conn_lock:
            reused = self._conn is not None
            try:
                return self._send(endpoint, data, timeout)
            except Exception:  # noqa: BLE001
                self._close_conn()
                if not reused or not retry_stale:
                    raise  # fresh conn failed (unreachable) or resend is unsafe
                # A kept-alive socket the server closed under us — reconnect once,
                # and leave a clean (closed) state if that retry also fails.
                try:
                    return self._send(endpoint, data, timeout)
                except Exception:  # noqa: BLE001
                    self._close_conn()
                    raise

    def _post(self, endpoint: str, body_obj: dict[str, Any],
              *, timeout: float | None = None) -> dict[str, Any]:
        # Command name for logging: unwrap the SysQuery/SysCtrl group, else use
        # the top-level key (e.g. query_record) directly.
        top = next(iter(body_obj))
        inner = body_obj[top]
        if isinstance(inner, dict) and top in ("SysQuery", "SysCtrl"):
            cmd_name = next(iter(inner), top)
        else:
            cmd_name = top
        data = p.szcmd(body_obj).encode("ascii")
        to = timeout if timeout is not None else self.timeout
        t0 = time.monotonic()
        try:
            # Queries are idempotent → safe to resend once over a stale socket.
            # SysCtrl mutates state (delete/format/reboot/settime) → never resend.
            raw = self._request(endpoint, data, to, retry_stale=(top != "SysCtrl"))
            result = p.parse_response(raw, command=cmd_name)
        except Exception as e:  # noqa: BLE001 — log then re-raise
            if debuglog.enabled():
                dur = (time.monotonic() - t0) * 1000
                debuglog.req("HTTP", cmd_name, dur, False,
                             f"{type(e).__name__}: {e}")
            raise
        if debuglog.enabled():
            dur = (time.monotonic() - t0) * 1000
            if debuglog.verbose():
                detail = f"body={p.szcmd(body_obj)!r} resp={raw[:400]!r}"
            elif cmd_name == "devicestate":
                st = result.get("stValue", {}) if isinstance(result, dict) else {}
                detail = f"vtx_connect={st.get('vtx_connect')}"
            else:
                detail = ""
            debuglog.req("HTTP", cmd_name, dur, True, detail)
        return result

    def _ajax(self, body_obj: dict[str, Any],
              *, timeout: float | None = None) -> dict[str, Any]:
        return self._post(p.EP_AJAXCOM, body_obj, timeout=timeout)

    def _query(self, body_obj: dict[str, Any],
               *, timeout: float | None = None) -> dict[str, Any]:
        return self._post(p.EP_QUERYDATA, body_obj, timeout=timeout)

    # --- system query -----------------------------------------------------

    def online(self) -> bool:
        return bool(self._ajax(p.CMD_ONLINE).get("stValue", {}).get("online"))

    def get_version(self) -> DeviceInfo:
        v = self._ajax(p.CMD_VERSION)["stValue"]
        return DeviceInfo(
            goggles_sn=v.get("Goggles_SN", ""),
            goggles_hw=v.get("Goggles_HW_Version", ""),
            goggles_sw=v.get("Goggles_SW_Version", ""),
            tx_sn=v.get("TX_SN", ""),
            tx_hw=v.get("TX_HW_Version", ""),
            tx_sw=v.get("TX_SW_Version", ""),
            raw=v,
        )

    def get_device_state(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Live telemetry. Key field: ``vtx_connect`` (1 when an air unit is linked).

        Pass a short ``timeout`` for the telemetry loop so a slow/booting goggles
        doesn't stall polling for the full control timeout.
        """
        return self._ajax(p.CMD_DEVICE_STATE, timeout=timeout)["stValue"]

    def vtx_connected(self) -> bool:
        return bool(self.get_device_state().get("vtx_connect"))

    # --- system control ---------------------------------------------------

    def set_time(self, when=None) -> None:
        self._ajax(p.cmd_set_time(when))

    def reboot(self) -> None:
        self._ajax(p.CMD_REBOOT)

    def update_reboot(self) -> None:
        """Apply an uploaded firmware image and reboot."""
        self._ajax(p.CMD_UPDATE_REBOOT)

    def factory_reset(self) -> None:
        self._ajax(p.CMD_FACTORY_DEFAULT)

    def format_goggles_sd(self) -> None:
        self._ajax(p.CMD_FORMAT_GOGGLES_SD)

    def format_vtx_sd(self) -> None:
        self._ajax(p.CMD_FORMAT_VTX_SD)

    # --- DVR records ------------------------------------------------------

    def list_records(self, start: int = 0, limit: int | None = None,
                     *, timeout: float | None = None) -> dict[str, Any]:
        """Return ``{"total": int, "rows": [{"szFileName", "duration"}, ...]}``.

        ``limit=None`` requests all records (the app's default sentinel).
        ``query_record`` is heavy on the goggles, so callers should pass a
        generous ``timeout`` (the control-plane default is too short under load).
        """
        cmd = (p.cmd_query_record(start) if limit is None
               else p.cmd_query_record(start, limit))
        return self._query(cmd, timeout=timeout)

    def record_url(self, filename: str) -> str:
        return p.record_url(filename, self.host)

    def download_record(self, filename: str, dest: str) -> str:
        """Download a DVR clip to ``dest`` (streamed). Returns ``dest``."""
        url = self.record_url(filename)
        # Long timeout: clips can be large; download is not a control call.
        t0 = time.monotonic()
        total = 0
        debuglog.event(f"[dvr] download start {filename}")
        try:
            with urllib.request.urlopen(url, timeout=max(self.timeout, 60)) as resp, \
                    open(dest, "wb") as fh:
                while chunk := resp.read(1 << 16):
                    fh.write(chunk)
                    total += len(chunk)
        except Exception as e:  # noqa: BLE001
            debuglog.req("DVR", f"download {filename}",
                         (time.monotonic() - t0) * 1000, False,
                         f"{type(e).__name__}: {e} ({total} bytes)")
            raise
        debuglog.req("DVR", f"download {filename}",
                     (time.monotonic() - t0) * 1000, True, f"{total} bytes")
        return dest

    def delete_record(self, filename: str) -> None:
        """Delete a DVR clip on the goggles SD by name (irreversible)."""
        self._ajax(p.cmd_delete_record(filename))

    # --- video ------------------------------------------------------------

    @property
    def rtsp_url(self) -> str:
        return p.rtsp_url(self.host)

"""Control-plane client for the Walksnail Goggles X.

Pure stdlib (urllib) so it runs anywhere with no dependencies. The device must
be reachable on its Wi-Fi AP (default host 192.168.42.1).
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

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


class WalksnailClient:
    """Synchronous HTTP control client.

    >>> c = WalksnailClient()
    >>> c.get_version().goggles_sw
    '39.44.15'
    """

    def __init__(self, host: str = p.DEFAULT_HOST, *, timeout: float = 5.0):
        self.host = host
        self.timeout = timeout
        self.base = f"http://{host}"

    # --- transport --------------------------------------------------------

    def _post(self, endpoint: str, body_obj: dict[str, Any]) -> dict[str, Any]:
        cmd_name = next(iter(next(iter(body_obj.values())).keys())) \
            if body_obj and isinstance(next(iter(body_obj.values())), dict) \
            else next(iter(body_obj))
        data = p.szcmd(body_obj).encode("ascii")
        req = urllib.request.Request(
            self.base + endpoint, data=data, method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Connection": "close",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return p.parse_response(resp.read(), command=cmd_name)

    def _ajax(self, body_obj: dict[str, Any]) -> dict[str, Any]:
        return self._post(p.EP_AJAXCOM, body_obj)

    def _query(self, body_obj: dict[str, Any]) -> dict[str, Any]:
        return self._post(p.EP_QUERYDATA, body_obj)

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

    def get_device_state(self) -> dict[str, Any]:
        """Live telemetry. Key field: ``vtx_connect`` (1 when an air unit is linked)."""
        return self._ajax(p.CMD_DEVICE_STATE)["stValue"]

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

    def list_records(self, start: int = 0, limit: int | None = None) -> dict[str, Any]:
        """Return ``{"total": int, "rows": [{"szFileName", "duration"}, ...]}``.

        ``limit=None`` requests all records (the app's default sentinel).
        """
        cmd = (p.cmd_query_record(start) if limit is None
               else p.cmd_query_record(start, limit))
        return self._query(cmd)

    def record_url(self, filename: str) -> str:
        return p.record_url(filename, self.host)

    def download_record(self, filename: str, dest: str) -> str:
        """Download a DVR clip to ``dest`` (streamed). Returns ``dest``."""
        url = self.record_url(filename)
        # Long timeout: clips can be large; download is not a control call.
        with urllib.request.urlopen(url, timeout=max(self.timeout, 60)) as resp, \
                open(dest, "wb") as fh:
            while chunk := resp.read(1 << 16):
                fh.write(chunk)
        return dest

    def delete_record(self, filename: str) -> None:
        """Delete a DVR clip on the goggles SD by name (irreversible)."""
        self._ajax(p.cmd_delete_record(filename))

    # --- video ------------------------------------------------------------

    @property
    def rtsp_url(self) -> str:
        return p.rtsp_url(self.host)

"""ws_client — cross-platform client for FPV goggles.

Reverse-engineered for interoperability (see ../../PROTOCOL_SPEC.md). The
control plane is dependency-free; the live view needs the ``[video]`` extra.
"""

from .client import DeviceInfo, WSClient
from .protocol import GogglesError, DEFAULT_HOST, rtsp_url

__all__ = ["WSClient", "DeviceInfo", "GogglesError", "DEFAULT_HOST", "rtsp_url"]
__version__ = "0.1.0"

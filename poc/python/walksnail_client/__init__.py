"""walksnail_client — cross-platform client for Walksnail Avatar HD Goggles X.

Reverse-engineered for interoperability (see ../../PROTOCOL_SPEC.md). The
control plane is dependency-free; the live view needs the ``[video]`` extra.
"""

from .client import DeviceInfo, WalksnailClient
from .protocol import GogglesError, DEFAULT_HOST, rtsp_url

__all__ = ["WalksnailClient", "DeviceInfo", "GogglesError", "DEFAULT_HOST", "rtsp_url"]
__version__ = "0.1.0"

"""Minimal connection example — prints device info and telemetry.

Run with your machine joined to the goggles Wi-Fi (Walksnail_XXXX):

    python examples/connect.py
"""

from walksnail_client import WalksnailClient


def main() -> None:
    c = WalksnailClient()  # default host 192.168.42.1
    print("online:", c.online())

    info = c.get_version()
    print(f"Goggles {info.goggles_sn}  SW {info.goggles_sw}  HW {info.goggles_hw}")
    print("air unit linked:", info.vtx_present)

    state = c.get_device_state()
    print(f"vtx_connect={state['vtx_connect']}  "
          f"goggles batt={state['gas_voltage']:.2f}V  "
          f"goggles temp={state['gas_tempeture']}C")


if __name__ == "__main__":
    main()

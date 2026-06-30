"""Unit tests for the pure protocol layer (no device needed)."""

import json

import pytest

from walksnail_client import protocol as p
from walksnail_client.protocol import GogglesError, parse_response


def test_szcmd_encoding():
    assert p.szcmd(p.CMD_VERSION) == 'szCmd={"SysQuery":{"version":{}}}'
    assert p.szcmd(p.CMD_DEVICE_STATE) == 'szCmd={"SysQuery":{"devicestate":0}}'


def test_query_record_default_matches_app_sentinel():
    cmd = p.cmd_query_record()
    assert cmd == {"query_record": {"start": 0, "limit": 1_215_752_191}}


def test_settime_shape():
    import datetime as dt
    cmd = p.cmd_set_time(dt.datetime(2026, 6, 29, 13, 5, 9))
    assert cmd["SysCtrl"]["settime"] == {
        "dwYear": 2026, "byMonth": 6, "byDay": 29,
        "byHour": 13, "byMinute": 5, "bySecond": 9,
    }


def test_delete_record():
    assert p.szcmd(p.cmd_delete_record("AvatarG0531.mp4")) == \
        'szCmd={"SysCtrl":{"deletegasrecord":{"szFileName":"AvatarG0531.mp4"}}}'


def test_control_commands():
    assert p.szcmd(p.CMD_REBOOT) == 'szCmd={"SysCtrl":{"reboot":{}}}'
    assert p.szcmd(p.CMD_UPDATE_REBOOT) == 'szCmd={"SysCtrl":{"updatereboot":{}}}'
    assert p.szcmd(p.CMD_FACTORY_DEFAULT) == 'szCmd={"SysCtrl":{"default":{}}}'
    assert p.szcmd(p.CMD_FORMAT_GOGGLES_SD) == 'szCmd={"SysCtrl":{"gassdcardformat":{}}}'
    assert p.szcmd(p.CMD_FORMAT_VTX_SD) == 'szCmd={"SysCtrl":{"vtxsdcardformat":{}}}'


def test_urls():
    assert p.rtsp_url() == "rtsp://192.168.42.1/live.ch01"
    assert p.record_url("AvatarG0531.mp4") == "http://192.168.42.1/record/AvatarG0531.mp4"
    assert p.rtsp_url("10.0.0.5") == "rtsp://10.0.0.5/live.ch01"


def test_parse_ok():
    raw = json.dumps({"nRetVal": 0, "stValue": {"online": 1}})
    assert parse_response(raw)["stValue"]["online"] == 1


def test_parse_error_raises():
    raw = json.dumps({"nRetVal": -100, "szError": ""})
    with pytest.raises(GogglesError) as ei:
        parse_response(raw, command="version")
    assert ei.value.ret == -100
    assert "version" in str(ei.value)


def test_parse_real_version_payload():
    # Captured from the goggles (SW 39.44.15).
    raw = json.dumps({"nRetVal": 0, "stValue": {
        "Goggles_HW_Version": "4.0", "Goggles_SN": "AvatarX_079060",
        "Goggles_SW_Version": "39.44.15", "TX_SN": "--------",
        "TX_HW_Version": "-.-", "TX_SW_Version": "-.-.-"}})
    data = parse_response(raw)
    assert data["stValue"]["Goggles_SW_Version"] == "39.44.15"

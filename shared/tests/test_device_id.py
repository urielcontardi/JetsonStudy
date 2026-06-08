import os
import pytest
from unittest.mock import patch
from orwell_shared.device_id import get_ext_id


def _mock_net(ifaces: dict, monkeypatch):
    """ifaces = {"eth0": "4c:bb:47:c1:33:1a", "lo": "00:00:00:00:00:00", ...}"""
    import pathlib

    class _FakePath:
        def __init__(self, path):
            self._path = str(path)

        def __truediv__(self, other):
            return _FakePath(f"{self._path}/{other}")

        def iterdir(self):
            return [_FakePath(f"/sys/class/net/{k}") for k in ifaces]

        @property
        def name(self):
            return self._path.split("/")[-1]

        def read_text(self):
            iface = self._path.split("/")[-2]
            if iface in ifaces and "address" in self._path:
                return ifaces[iface] + "\n"
            raise FileNotFoundError(self._path)

        def startswith(self, prefix):
            return str(self._path).startswith(prefix)

    monkeypatch.setattr("orwell_shared.device_id.Path", _FakePath)


def test_returns_ethernet_mac(monkeypatch):
    monkeypatch.setattr(
        "orwell_shared.device_id.Path",
        lambda p: _make_path_mock({
            "enP8p1s0": "4c:bb:47:c1:33:1a",
            "wlP1p1s0": "bc:d2:2c:13:6d:6b",
            "lo": "00:00:00:00:00:00",
        }, str(p)),
    )
    result = get_ext_id()
    assert result == "4cbb47c1331a"


def test_prefers_ethernet_over_wifi(monkeypatch):
    monkeypatch.setattr(
        "orwell_shared.device_id.Path",
        lambda p: _make_path_mock({
            "wlP1p1s0": "bc:d2:2c:13:6d:6b",
            "enP8p1s0": "4c:bb:47:c1:33:1a",
        }, str(p)),
    )
    result = get_ext_id()
    assert result == "4cbb47c1331a"


def test_skips_virtual_interfaces(monkeypatch):
    monkeypatch.setattr(
        "orwell_shared.device_id.Path",
        lambda p: _make_path_mock({
            "docker0": "02:42:ac:11:00:01",
            "veth123": "aa:bb:cc:dd:ee:ff",
            "tailscale0": "aa:bb:cc:00:00:01",
            "wlP1p1s0": "bc:d2:2c:13:6d:6b",
        }, str(p)),
    )
    result = get_ext_id()
    assert result == "bcd22c136d6b"


def test_falls_back_to_env_var(monkeypatch):
    monkeypatch.setenv("ORWELL_DEVICE_ID", "mydevice0011")
    monkeypatch.setattr(
        "orwell_shared.device_id.Path",
        lambda p: _make_path_mock({}, str(p)),
    )
    assert get_ext_id() == "mydevice0011"


def test_raises_when_no_interface_and_no_env(monkeypatch):
    monkeypatch.delenv("ORWELL_DEVICE_ID", raising=False)
    monkeypatch.setattr(
        "orwell_shared.device_id.Path",
        lambda p: _make_path_mock({}, str(p)),
    )
    with pytest.raises(RuntimeError, match="ORWELL_DEVICE_ID"):
        get_ext_id()


def test_mac_is_12_lowercase_hex(monkeypatch):
    monkeypatch.setattr(
        "orwell_shared.device_id.Path",
        lambda p: _make_path_mock({"eth0": "4C:BB:47:C1:33:1A"}, str(p)),
    )
    result = get_ext_id()
    assert result == "4cbb47c1331a"
    assert len(result) == 12
    assert all(c in "0123456789abcdef" for c in result)


# ── helpers ──────────────────────────────────────────────────────────────────

class _PathMock:
    def __init__(self, path: str, ifaces: dict):
        self._path = path
        self._ifaces = ifaces

    def __truediv__(self, other):
        return _PathMock(f"{self._path}/{other}", self._ifaces)

    def iterdir(self):
        return [_PathMock(f"/sys/class/net/{k}", self._ifaces) for k in self._ifaces]

    @property
    def name(self):
        return self._path.split("/")[-1]

    def read_text(self):
        parts = self._path.split("/")
        if "address" in parts:
            iface = parts[-2]
            if iface in self._ifaces:
                return self._ifaces[iface] + "\n"
        raise FileNotFoundError(self._path)


def _make_path_mock(ifaces: dict, path: str):
    return _PathMock(path, ifaces)

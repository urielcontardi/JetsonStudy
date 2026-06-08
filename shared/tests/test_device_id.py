import os
import pytest
from blake3 import blake3
from orwell_shared.device_id import get_ext_id


# ── device-tree serial (Jetson NX / NVMe) ────────────────────────────────────

def test_derives_ext_id_from_device_tree_serial(tmp_path):
    serial_file = tmp_path / "serial-number"
    serial_file.write_bytes(b"1424625032396\x00")  # device-tree inclui null byte

    result = get_ext_id(serial_path=str(serial_file), cid_path=str(tmp_path / "no_cid"))

    expected = blake3(b"1424625032396").hexdigest()
    assert result == expected


def test_known_jetson_ext_id(tmp_path):
    """Valor real do Jetson Orin NX do projeto."""
    serial_file = tmp_path / "serial-number"
    serial_file.write_bytes(b"1424625032396")

    result = get_ext_id(serial_path=str(serial_file), cid_path=str(tmp_path / "no_cid"))

    assert result == "1e2f2caf4860137f0d335514ef1182bfeb6af354c053c0e72130820dba5e19eb"


def test_strips_null_and_whitespace_from_serial(tmp_path):
    serial_file = tmp_path / "serial-number"
    serial_file.write_bytes(b"  1424625032396\x00\n")

    result = get_ext_id(serial_path=str(serial_file), cid_path=str(tmp_path / "no_cid"))

    expected = blake3(b"1424625032396").hexdigest()
    assert result == expected


# ── eMMC CID fallback (Jetson Nano / AGX) ────────────────────────────────────

def test_falls_back_to_emmc_cid_when_no_serial(tmp_path):
    cid = "0a0000004f4c4f3400000000159001d7"
    cid_file = tmp_path / "cid"
    cid_file.write_text(cid + "\n")

    result = get_ext_id(serial_path=str(tmp_path / "no_serial"), cid_path=str(cid_file))

    expected = blake3(bytes.fromhex(cid)).hexdigest()
    assert result == expected


# ── env var fallback (dev / CI) ───────────────────────────────────────────────

def test_falls_back_to_env_var_when_no_hardware(monkeypatch, tmp_path):
    monkeypatch.setenv("ORWELL_DEVICE_ID", "mydeviceid123")

    result = get_ext_id(
        serial_path=str(tmp_path / "no_serial"),
        cid_path=str(tmp_path / "no_cid"),
    )
    assert result == "mydeviceid123"


def test_raises_when_nothing_available(monkeypatch, tmp_path):
    monkeypatch.delenv("ORWELL_DEVICE_ID", raising=False)

    with pytest.raises(RuntimeError, match="ORWELL_DEVICE_ID"):
        get_ext_id(
            serial_path=str(tmp_path / "no_serial"),
            cid_path=str(tmp_path / "no_cid"),
        )


# ── propriedades gerais ───────────────────────────────────────────────────────

def test_ext_id_is_64_hex_chars(tmp_path):
    serial_file = tmp_path / "serial-number"
    serial_file.write_bytes(b"1424625032396")

    result = get_ext_id(serial_path=str(serial_file), cid_path=str(tmp_path / "no_cid"))

    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_same_serial_always_same_ext_id(tmp_path):
    serial_file = tmp_path / "serial-number"
    serial_file.write_bytes(b"1424625032396")

    assert (get_ext_id(str(serial_file), str(tmp_path / "x")) ==
            get_ext_id(str(serial_file), str(tmp_path / "x")))


def test_different_serials_produce_different_ids(tmp_path):
    s1 = tmp_path / "s1"
    s2 = tmp_path / "s2"
    s1.write_bytes(b"1424625032396")
    s2.write_bytes(b"1424625032397")

    assert get_ext_id(str(s1), str(tmp_path / "x")) != get_ext_id(str(s2), str(tmp_path / "x"))

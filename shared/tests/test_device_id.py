import os
import pytest
from blake3 import blake3
from orwell_shared.device_id import get_ext_id


def test_derives_ext_id_from_cid_file(tmp_path):
    cid = "0a0000004f4c4f3400000000159001d7"
    cid_file = tmp_path / "cid"
    cid_file.write_text(cid + "\n")

    result = get_ext_id(cid_path=str(cid_file))

    expected = blake3(bytes.fromhex(cid)).hexdigest()
    assert result == expected


def test_ext_id_is_64_hex_chars(tmp_path):
    cid_file = tmp_path / "cid"
    cid_file.write_text("0a0000004f4c4f3400000000159001d7")

    result = get_ext_id(cid_path=str(cid_file))

    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_different_cids_produce_different_ids(tmp_path):
    cid_a = tmp_path / "cid_a"
    cid_b = tmp_path / "cid_b"
    cid_a.write_text("0a0000004f4c4f3400000000159001d7")
    cid_b.write_text("0a0000004f4c4f3400000000159001d8")

    assert get_ext_id(str(cid_a)) != get_ext_id(str(cid_b))


def test_falls_back_to_env_var_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("ORWELL_DEVICE_ID", "mydeviceid123")
    result = get_ext_id(cid_path=str(tmp_path / "nonexistent"))
    assert result == "mydeviceid123"


def test_raises_when_no_cid_and_no_env(monkeypatch, tmp_path):
    monkeypatch.delenv("ORWELL_DEVICE_ID", raising=False)
    with pytest.raises(RuntimeError, match="ORWELL_DEVICE_ID"):
        get_ext_id(cid_path=str(tmp_path / "nonexistent"))


def test_same_cid_always_produces_same_id(tmp_path):
    cid_file = tmp_path / "cid"
    cid_file.write_text("0a0000004f4c4f3400000000159001d7")
    assert get_ext_id(str(cid_file)) == get_ext_id(str(cid_file))

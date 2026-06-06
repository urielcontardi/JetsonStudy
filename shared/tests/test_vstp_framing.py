from orwell_shared.vstp import encode_request_header, decode_response_header
from orwell_shared.vstp_pb2 import VstpResponseHeader


def _make_response(res: str, body: bytes = b"") -> bytes:
    """Monta um frame de resposta VSTP válido."""
    h = VstpResponseHeader()
    h.res = res
    h.body_length = len(body)
    h_bytes = h.SerializeToString()
    return bytes([len(h_bytes)]) + h_bytes + body


def test_encode_ping():
    frame = encode_request_header("ping", b"")
    assert len(frame) >= 2
    header_size = frame[0]
    assert header_size > 0


def test_encode_with_body():
    body = b"hello world"
    frame = encode_request_header("pdevsample:abc:secret:abc", body)
    header_size = frame[0]
    assert frame[1 + header_size:] == body


def test_decode_ok_no_body():
    raw = _make_response("OK")
    res, body = decode_response_header(raw)
    assert res == "OK"
    assert body == b""


def test_decode_ok_with_body():
    raw = _make_response("OK", b"\x0a\x05token")
    res, body = decode_response_header(raw)
    assert res == "OK"
    assert body == b"\x0a\x05token"


def test_decode_error_response():
    raw = _make_response("FailToAuth")
    res, body = decode_response_header(raw)
    assert res == "FailToAuth"
    assert body == b""


def test_roundtrip_req_field():
    """O campo req do header deve ser preservado na serialização."""
    from orwell_shared.vstp_pb2 import VstpRequestHeader
    frame = encode_request_header("pdevsample:aabbccdd:mysecret:aabbccdd", b"payload")
    header_size = frame[0]
    h = VstpRequestHeader()
    h.ParseFromString(frame[1:1 + header_size])
    assert h.req == "pdevsample:aabbccdd:mysecret:aabbccdd"
    assert h.body_length == len(b"payload")
    assert h.keep_alive is False

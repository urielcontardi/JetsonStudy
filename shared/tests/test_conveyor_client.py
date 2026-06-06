import socketserver
import threading

import pytest
from blake3 import blake3

from orwell_shared.vstp import encode_request_header, decode_response_header
from orwell_shared.vstp_pb2 import VstpResponseHeader
from orwell_shared.gateway_pb2 import GetTokenResponseBody
from orwell_shared.conveyor_client import ConveyorClient


def _make_ok_response(body: bytes = b"") -> bytes:
    h = VstpResponseHeader()
    h.res = "OK"
    h.body_length = len(body)
    h_bytes = h.SerializeToString()
    return bytes([len(h_bytes)]) + h_bytes + body


def _make_token_body(token="tok", salt=0, length=10, num_requests=100) -> bytes:
    tb = GetTokenResponseBody()
    tb.token = token
    tb.salt = salt
    tb.length = length
    tb.num_requests = num_requests
    return tb.SerializeToString()


class _MockConveyor(socketserver.BaseRequestHandler):
    """Mock TCP handler: lê um frame VSTP completo (header + body) e responde."""

    responses: list

    def handle(self):
        from orwell_shared.vstp_pb2 import VstpRequestHeader

        size_byte = self.request.recv(1)
        if not size_byte:
            return
        header_size = size_byte[0]

        header_data = b""
        while len(header_data) < header_size:
            chunk = self.request.recv(header_size - len(header_data))
            if not chunk:
                return
            header_data += chunk

        req_header = VstpRequestHeader()
        req_header.ParseFromString(header_data)

        remaining = req_header.body_length
        while remaining > 0:
            chunk = self.request.recv(min(remaining, 4096))
            if not chunk:
                break
            remaining -= len(chunk)

        if _MockConveyor.responses:
            response = _MockConveyor.responses.pop(0)
        else:
            response = _make_ok_response()
        self.request.sendall(response)


def _start_mock_server(responses: list) -> tuple[socketserver.TCPServer, int]:
    _MockConveyor.responses = responses
    server = socketserver.TCPServer(("127.0.0.1", 0), _MockConveyor)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()
    return server, port


def test_ping_returns_true():
    token_bytes = _make_token_body()
    server, port = _start_mock_server([
        _make_ok_response(token_bytes),  # ggt response
        _make_ok_response(),             # ping response
    ])
    try:
        client = ConveyorClient("127.0.0.1", port, "aabbccddee00")
        result = client.ping()
        assert result is True
    finally:
        server.shutdown()


def test_send_dev_sample_does_not_raise():
    token_bytes = _make_token_body()
    server, port = _start_mock_server([
        _make_ok_response(token_bytes),  # ggt
        _make_ok_response(),             # pdevsample
    ])
    try:
        client = ConveyorClient("127.0.0.1", port, "aabbccddee00")
        client.send_dev_sample(b"fake-package-bytes")
    finally:
        server.shutdown()


def test_send_dev_status_does_not_raise():
    token_bytes = _make_token_body()
    server, port = _start_mock_server([
        _make_ok_response(token_bytes),  # ggt
        _make_ok_response(),             # pdevstatus
    ])
    try:
        client = ConveyorClient("127.0.0.1", port, "aabbccddee00")
        client.send_dev_status(b"fake-status-bytes")
    finally:
        server.shutdown()


def test_secret_derivation_matches_emulator_logic():
    ext_id = "aabbccddee00"
    token = "mytoken123"
    salt = 2
    length = 8

    blake3_hash = blake3(ext_id.encode()).hexdigest()
    hash_input = blake3_hash + token
    expected_secret = blake3(hash_input.encode()).hexdigest()[salt : salt + length]

    token_bytes = _make_token_body(token=token, salt=salt, length=length, num_requests=10)
    server, port = _start_mock_server([
        _make_ok_response(token_bytes),
        _make_ok_response(),
    ])
    try:
        client = ConveyorClient("127.0.0.1", port, ext_id)
        secret = client._get_secret()
        assert secret == expected_secret
    finally:
        server.shutdown()


def test_raises_on_auth_failure():
    h = VstpResponseHeader()
    h.res = "FailToAuth"
    h_bytes = h.SerializeToString()
    fail_response = bytes([len(h_bytes)]) + h_bytes

    server, port = _start_mock_server([fail_response])
    try:
        with pytest.raises(RuntimeError, match="Auth failed"):
            ConveyorClient("127.0.0.1", port, "aabbccddee00")
    finally:
        server.shutdown()

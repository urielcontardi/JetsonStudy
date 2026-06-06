from __future__ import annotations

from orwell_shared.vstp_pb2 import VstpRequestHeader, VstpResponseHeader


def encode_request_header(req: str, body: bytes) -> bytes:
    header = VstpRequestHeader()
    header.req = req
    header.body_length = len(body)
    header.keep_alive = False
    header_bytes = header.SerializeToString()
    return bytes([len(header_bytes)]) + header_bytes + body


def decode_response_header(data: bytes) -> tuple[str, bytes]:
    if not data:
        raise ValueError("empty VSTP response")
    header_size = data[0]
    header = VstpResponseHeader()
    header.ParseFromString(data[1 : 1 + header_size])
    body = data[1 + header_size :]
    return header.res, body

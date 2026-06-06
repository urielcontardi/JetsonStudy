from __future__ import annotations

import socket
import threading

from blake3 import blake3

from orwell_shared.gateway_pb2 import GetTokenResponseBody
from orwell_shared.vstp import decode_response_header, encode_request_header


class ConveyorClient:
    def __init__(
        self,
        host: str,
        port: int,
        ext_id: str,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._ext_id = ext_id
        self._timeout = timeout
        self._blake3_hash = blake3(ext_id.encode()).hexdigest()
        self._token: dict | None = None
        self._secret: str = ""
        self._lock = threading.Lock()
        self._get_auth()

    def _send(self, data: bytes) -> bytes:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(self._timeout)
            s.connect((self._host, self._port))
            s.sendall(data)
            chunks: list[bytes] = []
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)

    def _get_auth(self) -> None:
        req = f"ggt:{self._ext_id}"
        response = self._send(encode_request_header(req, b""))
        res, body = decode_response_header(response)
        if res != "OK":
            raise RuntimeError(f"Auth failed: {res}")
        tb = GetTokenResponseBody()
        tb.ParseFromString(body)
        self._token = {
            "token": tb.token,
            "salt": tb.salt,
            "length": tb.length,
            "num_requests": tb.num_requests,
        }
        self._secret = ""

    def _get_secret(self) -> str:
        assert self._token is not None
        if self._token["num_requests"] == 0:
            self._get_auth()
        if not self._secret:
            hash_input = self._blake3_hash + self._token["token"]
            blake_hash = blake3(hash_input.encode()).hexdigest()
            self._secret = blake_hash[
                self._token["salt"] : self._token["salt"] + self._token["length"]
            ]
        self._token["num_requests"] -= 1
        return self._secret

    def ping(self) -> bool:
        response = self._send(encode_request_header("ping", b""))
        res, _ = decode_response_header(response)
        return res == "OK"

    def send_dev_sample(self, body: bytes) -> None:
        with self._lock:
            secret = self._get_secret()
            req = f"pdevsample:{self._ext_id}:{secret}:{self._ext_id}"
            response = self._send(encode_request_header(req, body))
            res, _ = decode_response_header(response)
            if res != "OK":
                raise RuntimeError(f"pdevsample failed: {res}")

    def send_dev_status(self, body: bytes) -> None:
        with self._lock:
            secret = self._get_secret()
            req = f"pdevstatus:{self._ext_id}:{secret}:{self._ext_id}"
            response = self._send(encode_request_header(req, body))
            res, _ = decode_response_header(response)
            if res != "OK":
                raise RuntimeError(f"pdevstatus failed: {res}")

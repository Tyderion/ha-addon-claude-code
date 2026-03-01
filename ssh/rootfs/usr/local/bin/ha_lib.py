"""ha_lib — Shared WebSocket library for Home Assistant CLI tools.

Provides a singleton WebSocket connection that is opened lazily on the first
ha_call() and reused for all subsequent calls within the same process.

Public API:
    get_token() -> str
    ha_call(command: dict) -> dict
"""

import atexit
import base64
import json
import os
import socket
import struct
import sys

HA_HOST = "localhost"
HA_PORT = 8123
TOKEN_FILE = "/homeassistant/.claude/ha_token"

# Module-level singleton state
_ws = None
_msg_id = 0


def get_token() -> str:
    token = os.environ.get("HA_TOKEN")
    if not token and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
    if not token:
        print(
            "Error: No HA token found.\n"
            "Set HA_TOKEN env var or create a long-lived token:\n"
            "  HA UI → Profile → Security → Long-Lived Access Tokens → Create Token\n"
            f"  echo 'your_token' > {TOKEN_FILE}\n"
            f"  chmod 600 {TOKEN_FILE}",
            file=sys.stderr,
        )
        sys.exit(1)
    return token


class WS:
    """Minimal WebSocket client with a persistent receive buffer.

    HA sends the first frame (auth_required) in the same TCP segment as the
    HTTP 101 response, so we must carry over any bytes past the header boundary.
    """

    def __init__(self):
        self._sock = socket.create_connection((HA_HOST, HA_PORT), timeout=30)
        self._buf = b""
        self._handshake()

    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET /api/websocket HTTP/1.1\r\n"
            f"Host: {HA_HOST}:{HA_PORT}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self._sock.sendall(request.encode())

        while b"\r\n\r\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("Connection closed during WebSocket handshake")
            self._buf += chunk

        end = self._buf.index(b"\r\n\r\n") + 4
        headers, self._buf = self._buf[:end], self._buf[end:]

        if b"101" not in headers.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WebSocket upgrade failed: {headers[:200]}")

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("Connection closed while reading")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def recv(self) -> dict:
        header = self._read(2)
        masked = (header[1] & 0x80) != 0
        length = header[1] & 0x7F

        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]

        mask = self._read(4) if masked else b""
        payload = self._read(length)

        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

        return json.loads(payload.decode())

    def send(self, data: dict):
        payload = json.dumps(data).encode()
        length = len(payload)
        mask_key = os.urandom(4)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        if length < 126:
            header = bytes([0x81, 0x80 | length]) + mask_key
        elif length < 65536:
            header = bytes([0x81, 0xFE]) + struct.pack(">H", length) + mask_key
        else:
            header = bytes([0x81, 0xFF]) + struct.pack(">Q", length) + mask_key

        self._sock.sendall(header + masked)

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


def _ensure_connection():
    """Open and authenticate the singleton WebSocket connection if needed."""
    global _ws
    if _ws is not None:
        return

    _ws = WS()

    msg = _ws.recv()
    if msg.get("type") != "auth_required":
        raise RuntimeError(f"Expected auth_required, got: {msg}")

    _ws.send({"type": "auth", "access_token": get_token()})
    msg = _ws.recv()
    if msg.get("type") != "auth_ok":
        raise RuntimeError(
            "Authentication failed. Check your token in "
            f"HA_TOKEN env var or {TOKEN_FILE}"
        )

    atexit.register(_cleanup)


def _cleanup():
    global _ws
    if _ws is not None:
        _ws.close()
        _ws = None


def ha_call(command: dict) -> dict:
    """Send a command over the singleton WebSocket and return the response.

    The connection is opened and authenticated lazily on the first call.
    Subsequent calls reuse the same connection. Unsolicited messages
    (events, etc.) with non-matching IDs are discarded.
    """
    global _msg_id

    _ensure_connection()

    _msg_id += 1
    command["id"] = _msg_id
    _ws.send(command)

    # Read until we get the response matching our ID
    while True:
        msg = _ws.recv()
        if msg.get("id") == _msg_id:
            return msg

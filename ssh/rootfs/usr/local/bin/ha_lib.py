"""ha_lib — Shared WebSocket library for Home Assistant CLI tools.

Provides a singleton WebSocket connection that is opened lazily on the first
ha_call() and reused for all subsequent calls within the same process.

Public API:
    get_token() -> str
    ha_call(command: dict) -> dict
    ha_result(command: dict) -> the command's unwrapped "result"
    ha_subscribe(command: dict) -> generator of event payloads

All helpers raise RuntimeError when HA reports failure.
"""

import atexit
import base64
import json
import os
import socket
import struct
import sys
import time

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

    def _read_frame(self):
        """Read one WebSocket frame; return (fin, opcode, payload)."""
        header = self._read(2)
        fin = (header[0] & 0x80) != 0
        opcode = header[0] & 0x0F
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

        return fin, opcode, payload

    def recv(self) -> dict:
        """Receive one JSON message, handling control frames and fragmentation."""
        message = b""
        while True:
            fin, opcode, payload = self._read_frame()
            if opcode == 0x9:  # ping → reply with pong
                self._send_frame(0xA, payload)
            elif opcode == 0xA:  # pong → ignore
                pass
            elif opcode == 0x8:  # close
                raise RuntimeError("Server closed the WebSocket connection")
            elif opcode in (0x1, 0x0):  # text / continuation
                message += payload
                if fin:
                    return json.loads(message.decode())
            else:
                raise RuntimeError(f"Unsupported WebSocket frame (opcode {opcode:#x})")

    def _send_frame(self, opcode: int, payload: bytes):
        length = len(payload)
        mask_key = os.urandom(4)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        first = 0x80 | opcode

        if length < 126:
            header = bytes([first, 0x80 | length]) + mask_key
        elif length < 65536:
            header = bytes([first, 0xFE]) + struct.pack(">H", length) + mask_key
        else:
            header = bytes([first, 0xFF]) + struct.pack(">Q", length) + mask_key

        self._sock.sendall(header + masked)

    def send(self, data: dict):
        self._send_frame(0x1, json.dumps(data).encode())

    def close(self):
        try:
            self._send_frame(0x8, struct.pack(">H", 1000))  # clean close, code 1000
            self._sock.close()
        except Exception:
            pass


def _ensure_connection():
    """Open and authenticate the singleton WebSocket connection if needed."""
    global _ws
    if _ws is not None:
        return

    ws = WS()
    try:
        msg = ws.recv()
        if msg.get("type") != "auth_required":
            raise RuntimeError(f"Expected auth_required, got: {msg}")

        ws.send({"type": "auth", "access_token": get_token()})
        msg = ws.recv()
        if msg.get("type") != "auth_ok":
            raise RuntimeError(
                "Authentication failed. Check your token in "
                f"HA_TOKEN env var or {TOKEN_FILE}"
            )
    except BaseException:
        # Never leave a broken, unauthenticated socket as the singleton
        ws.close()
        raise

    _ws = ws
    atexit.register(_cleanup)


def _cleanup():
    global _ws
    if _ws is not None:
        _ws.close()
        _ws = None


def ha_call(command: dict, timeout: float = 60.0) -> dict:
    """Send a command over the singleton WebSocket and return the response.

    The connection is opened and authenticated lazily on the first call.
    Subsequent calls reuse the same connection. Unsolicited messages
    (events, etc.) with non-matching IDs are discarded.

    Raises RuntimeError if HA reports the command failed (success: false)
    or no response arrives within `timeout` seconds.
    """
    global _msg_id

    _ensure_connection()

    _msg_id += 1
    _ws.send({**command, "id": _msg_id})

    # Read until we get the response matching our ID
    deadline = time.monotonic() + timeout
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"Timed out waiting for response to '{command.get('type')}'"
            )
        try:
            msg = _ws.recv()
        except socket.timeout:
            raise RuntimeError(
                f"Timed out waiting for response to '{command.get('type')}'"
            ) from None
        if msg.get("id") != _msg_id:
            continue
        if msg.get("success") is False:
            error = msg.get("error", {})
            if isinstance(error, dict):
                code = f" ({error['code']})" if error.get("code") else ""
                detail = f"{error.get('message', 'unknown error')}{code}"
            else:
                detail = str(error)
            raise RuntimeError(f"'{command.get('type')}' failed: {detail}")
        return msg


def ha_result(command: dict):
    """Run a command and return its unwrapped "result" payload."""
    return ha_call(command).get("result")


def ha_subscribe(command: dict, timeout: float = 60.0):
    """Send a subscription command and yield each event payload as it arrives.

    Consumes the success acknowledgement first (raising RuntimeError on
    failure), then yields the "event" payload of every matching event message.
    `timeout` bounds the wait for the ack and the first event; after that the
    stream is unbounded — idle socket timeouts trigger a WebSocket ping so a
    dead connection is detected instead of blocking forever.

    The subscription is never cancelled; intended for CLI processes that exit
    (and close the connection) when done.
    """
    global _msg_id

    _ensure_connection()

    _msg_id += 1
    sub_id = _msg_id
    _ws.send({**command, "id": sub_id})

    deadline = time.monotonic() + timeout
    got_event = False
    while True:
        if not got_event and time.monotonic() > deadline:
            raise RuntimeError(f"Timed out waiting for '{command.get('type')}'")
        try:
            msg = _ws.recv()
        except socket.timeout:
            if not got_event:
                raise RuntimeError(
                    f"Timed out waiting for '{command.get('type')}'"
                ) from None
            _ws._send_frame(0x9, b"keepalive")  # liveness probe; pong is swallowed
            continue
        if msg.get("id") != sub_id:
            continue
        if msg.get("type") == "result":
            if msg.get("success") is False:
                error = msg.get("error", {})
                if isinstance(error, dict):
                    code = f" ({error['code']})" if error.get("code") else ""
                    detail = f"{error.get('message', 'unknown error')}{code}"
                else:
                    detail = str(error)
                raise RuntimeError(f"'{command.get('type')}' failed: {detail}")
            continue
        if msg.get("type") == "event":
            got_event = True
            yield msg.get("event")

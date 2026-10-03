"""ha_lib — Shared WebSocket library for Home Assistant CLI tools.

Provides a singleton WebSocket connection that is opened lazily on the first
ha_call() and reused for all subsequent calls within the same process.

Public API:
    get_token() -> str
    ha_call(command: dict) -> dict
    ha_result(command: dict) -> the command's unwrapped "result"
    ha_subscribe(command: dict) -> generator of event payloads
    ha_http(method: str, path: str, body=None) -> decoded JSON reply
    print_output(data, fmt), FORMAT_PARENT, run_cli(parser, extra_errors=())
    json_or_str(value), parse_pairs(pairs, flag) -> dict

All helpers raise RuntimeError when HA reports failure; ha_http raises its
subclass HAHTTPError, which carries the status and the decoded reply body,
and HATimeout when HA accepted the request but did not answer in time.
Some APIs (config flows, config entry reload/remove) exist only as REST
views, which is what ha_http is for.
"""

import argparse
import atexit
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.error
import urllib.request

import yaml

HA_HOST = "localhost"
HA_PORT = 8123
TOKEN_FILE = "/homeassistant/.claude/ha_token"
# Socket timeout for connecting, the handshake and auth. It is also the resting
# timeout between calls, which paces ha_subscribe's idle liveness pings;
# ha_call and ha_subscribe narrow it to their own deadline while they wait.
SOCKET_TIMEOUT = 30.0

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
        self._sock = socket.create_connection(
            (HA_HOST, HA_PORT), timeout=SOCKET_TIMEOUT
        )
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

    def settimeout(self, seconds: float):
        self._sock.settimeout(seconds)

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


def _send(command: dict) -> int:
    """Send a command on the singleton connection and return its message id."""
    global _msg_id

    _ensure_connection()
    _msg_id += 1
    _ws.send({**command, "id": _msg_id})
    return _msg_id


def _raise_on_failure(msg: dict, command: dict):
    """Raise RuntimeError with HA's error detail if `msg` reports success: false."""
    if msg.get("success") is not False:
        return
    error = msg.get("error", {})
    if isinstance(error, dict):
        code = f" ({error['code']})" if error.get("code") else ""
        detail = f"{error.get('message', 'unknown error')}{code}"
    else:
        detail = str(error)
    raise RuntimeError(f"'{command.get('type')}' failed: {detail}")


def _recv_until(deadline: float, what: str) -> dict:
    """Receive one message, raising RuntimeError once `deadline` has passed.

    `deadline` is a time.monotonic() value. The socket waits only for the
    time that is left (at least 0.1 s), then goes back to SOCKET_TIMEOUT.
    A socket timeout may strike mid-frame, leaving the stream unreadable, so
    it also drops the connection; the next call opens a fresh one.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError(f"Timed out waiting for {what}")
    _ws.settimeout(max(remaining, 0.1))
    try:
        return _ws.recv()
    except socket.timeout:
        _cleanup()
        raise RuntimeError(f"Timed out waiting for {what}") from None
    finally:
        if _ws is not None:
            _ws.settimeout(SOCKET_TIMEOUT)


def ha_call(command: dict, timeout: float = 60.0) -> dict:
    """Send a command over the singleton WebSocket and return the response.

    The connection is opened and authenticated lazily on the first call.
    Subsequent calls reuse the same connection. Unsolicited messages
    (events, etc.) with non-matching IDs are discarded.

    Raises RuntimeError if HA reports the command failed (success: false)
    or no response arrives within `timeout` seconds.
    """
    msg_id = _send(command)

    # Read until we get the response matching our ID
    deadline = time.monotonic() + timeout
    while True:
        msg = _recv_until(deadline, f"response to '{command.get('type')}'")
        if msg.get("id") != msg_id:
            continue
        _raise_on_failure(msg, command)
        return msg


def ha_result(command: dict):
    """Run a command and return its unwrapped "result" payload."""
    return ha_call(command).get("result")


def ha_subscribe(command: dict, timeout: float = 60.0):
    """Send a subscription command and yield each event payload as it arrives.

    Consumes the success acknowledgement first (raising RuntimeError on
    failure), then yields the "event" payload of every matching event message.
    `timeout` bounds the wait for the ack and the first event; after that the
    stream is unbounded — every SOCKET_TIMEOUT of silence triggers a
    WebSocket ping so a dead connection is detected instead of blocking
    forever.

    The subscription is never cancelled; intended for CLI processes that exit
    (and close the connection) when done.
    """
    sub_id = _send(command)

    deadline = time.monotonic() + timeout
    got_event = False
    while True:
        if not got_event:
            msg = _recv_until(deadline, f"'{command.get('type')}'")
        else:
            try:
                msg = _ws.recv()
            except socket.timeout:
                _ws._send_frame(0x9, b"keepalive")  # liveness probe; pong is swallowed
                continue
        if msg.get("id") != sub_id:
            continue
        if msg.get("type") == "result":
            _raise_on_failure(msg, command)
            continue
        if msg.get("type") == "event":
            got_event = True
            yield msg.get("event")


class HAHTTPError(RuntimeError):
    """A REST call answered with a non-2xx status.

    `status` is the HTTP status and `body` the decoded reply (a dict for JSON
    replies, else the text), so callers can read structured errors such as a
    config flow's {"errors": {...}}.
    """

    def __init__(self, method: str, path: str, status: int, body):
        self.status = status
        self.body = body
        detail = body.get("message") if isinstance(body, dict) else body
        message = f"{method} {path} failed: HTTP {status}"
        if detail:
            message += f": {detail}"
        if status == 401:
            message += " (the token's user must be an administrator)"
        super().__init__(message)


class HATimeout(RuntimeError):
    """A REST call got no answer in time; HA may still be processing it."""


def _decode(raw: bytes):
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def ha_http(method: str, path: str, body=None, timeout: float = 60.0):
    """Call Home Assistant's REST API and return the decoded JSON reply.

    `path` starts with /api/. `body`, if given, is sent as JSON. Raises
    HAHTTPError on a non-2xx status, HATimeout when the answer does not come
    within `timeout`, and RuntimeError if HA is unreachable.
    """
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"http://{HA_HOST}:{HA_PORT}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {get_token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _decode(response.read())
    except urllib.error.HTTPError as e:
        raise HAHTTPError(method, path, e.code, _decode(e.read())) from None
    except socket.timeout:
        # The request went out; only the answer is missing
        raise HATimeout(
            f"{method} {path}: no answer from Home Assistant within {timeout:g}s"
        ) from None
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        raise RuntimeError(
            f"cannot reach Home Assistant at {HA_HOST}:{HA_PORT}: {reason}"
        ) from None


# --- Shared CLI scaffolding ---


def print_output(data, fmt):
    """Print `data` as JSON (fmt == "json") or YAML."""
    if fmt == "json":
        print(json.dumps(data, indent=2, default=str))
    else:
        print(
            yaml.safe_dump(
                data, sort_keys=False, allow_unicode=True, default_flow_style=False
            ),
            end="",
        )


# argparse parent giving a subcommand its --format option
FORMAT_PARENT = argparse.ArgumentParser(add_help=False)
FORMAT_PARENT.add_argument(
    "--format",
    choices=["yaml", "json"],
    default="yaml",
    help="Output format (default: yaml)",
)


def run_cli(parser, extra_errors=()):
    """Parse args, run the subcommand's `func`, and turn failures into exit 1.

    `extra_errors` are exceptions that mean Home Assistant sent a reply of an
    unexpected shape (e.g. KeyError, TypeError); they get that wording.
    """
    args = parser.parse_args()
    try:
        args.func(args)
    except (RuntimeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except extra_errors as e:
        print(
            f"Error: unexpected reply from Home Assistant ({type(e).__name__}: {e})",
            file=sys.stderr,
        )
        sys.exit(1)


def json_or_str(value: str):
    """Parse `value` as JSON, falling back to the raw string."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def parse_pairs(pairs, flag: str) -> dict:
    """Turn repeated KEY=VALUE options into a dict; values are JSON when possible."""
    result = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise RuntimeError(f"{flag} expects KEY=VALUE, got '{pair}'")
        result[key] = json_or_str(value)
    return result

#!/usr/bin/env python3
"""Unit tests for the WebSocket waits in `ha_lib` (ha_call, ha_subscribe).

The connection is replaced by a fake WebSocket on a virtual clock: messages
are scheduled at given times, and a recv() that would wait longer than the
socket timeout advances the clock by that timeout and raises socket.timeout,
the way a real socket does. Nothing sleeps, so the tests run instantly.

Run: python3 ssh/tests/test_ha_lib.py
"""

import socket
import types
import unittest

from toolharness import load_ha_lib

# What the real connection sets on connect; the fake starts with it too
CONNECT_TIMEOUT = 30.0


class FakeWS:
    """A WebSocket whose messages arrive at scheduled virtual times.

    `schedule` is a list of (time, message); a message whose "id" is "ID"
    gets the id of the last command sent.
    """

    def __init__(self, lib, schedule):
        self.lib = lib
        self.now = 0.0
        self.timeout = CONNECT_TIMEOUT
        self.schedule = sorted(schedule, key=lambda item: item[0])
        self.pings = []
        self.closed = False

    def monotonic(self):
        return self.now

    def settimeout(self, seconds):
        self.timeout = seconds

    def send(self, data):
        pass

    def _send_frame(self, opcode, payload):
        if opcode == 0x9:
            self.pings.append(self.now)

    def close(self):
        self.closed = True

    def recv(self):
        if not self.schedule or self.schedule[0][0] - self.now > self.timeout:
            self.now += self.timeout
            raise socket.timeout("timed out")
        at, msg = self.schedule.pop(0)
        self.now = max(self.now, at)
        if msg.get("id") == "ID":
            msg = {**msg, "id": self.lib._msg_id}
        return msg


class Base(unittest.TestCase):
    def connect(self, schedule):
        self.lib = load_ha_lib()
        self.ws = FakeWS(self.lib, schedule)
        self.lib._ws = self.ws
        self.lib.time = types.SimpleNamespace(monotonic=self.ws.monotonic)
        return self.ws


def result(at, **extra):
    return (at, {"id": "ID", "type": "result", "success": True, **extra})


def event(at, payload):
    return (at, {"id": "ID", "type": "event", "event": payload})


class HaCallTimeout(Base):
    def test_waits_past_the_connect_timeout_when_asked(self):
        self.connect([result(40, result="late")])
        msg = self.lib.ha_call({"type": "slow"}, timeout=45)
        self.assertEqual(msg["result"], "late")

    def test_gives_up_at_its_own_deadline(self):
        ws = self.connect([result(10)])
        with self.assertRaisesRegex(RuntimeError, "response to 'slow'"):
            self.lib.ha_call({"type": "slow"}, timeout=5)
        self.assertAlmostEqual(ws.now, 5, delta=0.2)

    def test_unrelated_traffic_does_not_extend_the_deadline(self):
        ws = self.connect([(t, {"id": 999, "type": "event"}) for t in range(1, 20)])
        with self.assertRaisesRegex(RuntimeError, "Timed out"):
            self.lib.ha_call({"type": "slow"}, timeout=5.5)
        self.assertLess(ws.now, 6.5)

    def test_socket_timeout_restored_after_the_call(self):
        ws = self.connect([result(1)])
        self.lib.ha_call({"type": "quick"}, timeout=5)
        self.assertEqual(ws.timeout, self.lib.SOCKET_TIMEOUT)

    def test_failure_still_raises(self):
        self.connect([(1, {"id": "ID", "type": "result", "success": False})])
        with self.assertRaisesRegex(RuntimeError, "'bad' failed"):
            self.lib.ha_call({"type": "bad"}, timeout=5)


class Reconnect(unittest.TestCase):
    """A timed-out call drops the connection, which may hold half a frame."""

    def test_next_call_after_a_timeout_opens_a_fresh_connection(self):
        lib = load_ha_lib()
        conns = []

        def connect():
            # Each connection authenticates, then answers one command at t+1
            start = conns[-1].now if conns else 0.0
            ws = FakeWS(lib, [])
            ws.now = start
            ws.schedule = [
                (start, {"type": "auth_required"}),
                (start, {"type": "auth_ok"}),
                result(start + (10 if not conns else 1), result=len(conns) + 1),
            ]
            conns.append(ws)
            return ws

        lib.WS = connect
        lib.get_token = lambda: "token"
        lib.time = types.SimpleNamespace(monotonic=lambda: conns[-1].now)

        with self.assertRaisesRegex(RuntimeError, "Timed out"):
            lib.ha_call({"type": "slow"}, timeout=5)
        self.assertIsNone(lib._ws)
        self.assertTrue(conns[0].closed)

        msg = lib.ha_call({"type": "quick"}, timeout=5)
        self.assertEqual(len(conns), 2)
        self.assertEqual(msg["result"], 2)


class HaSubscribeTimeout(Base):
    def test_first_event_may_come_after_the_connect_timeout(self):
        self.connect([result(1), event(40, "first")])
        stream = self.lib.ha_subscribe({"type": "watch"}, timeout=45)
        self.assertEqual(next(stream), "first")

    def test_gives_up_at_its_own_deadline(self):
        ws = self.connect([result(1), event(20, "late")])
        stream = self.lib.ha_subscribe({"type": "watch"}, timeout=5)
        with self.assertRaisesRegex(RuntimeError, "Timed out waiting for 'watch'"):
            next(stream)
        self.assertAlmostEqual(ws.now, 5, delta=0.2)

    def test_idle_stream_pings_every_socket_timeout(self):
        ws = self.connect([result(1), event(2, "first"), event(80, "second")])
        stream = self.lib.ha_subscribe({"type": "watch"}, timeout=5)
        self.assertEqual(next(stream), "first")
        self.assertEqual(next(stream), "second")
        self.assertEqual(ws.pings, [32.0, 62.0])


if __name__ == "__main__":
    unittest.main()

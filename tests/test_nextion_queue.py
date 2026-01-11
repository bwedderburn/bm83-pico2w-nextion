"""Focused Nextion queue tests to guard against inefficient queue operations."""

from __future__ import annotations

import importlib.util
import sys
import types
from collections import deque
from pathlib import Path


class DummyUART:
    """Minimal UART stub for exercising the Nextion queue."""

    def __init__(self, *_, **__):
        self.in_waiting = 0
        self.writes: list[bytes] = []

    def write(self, data: bytes):
        self.writes.append(data)

    def read(self, _n: int):
        return None


def load_code_module():
    """Load firmware/circuitpython/code.py with hardware stubs injected."""
    firmware_dir = Path(__file__).parent.parent / "firmware" / "circuitpython"
    code_path = firmware_dir / "code.py"

    # Provide lightweight stubs so import succeeds on host.
    sys.modules.setdefault(
        "board",
        types.SimpleNamespace(IO15=1, IO16=2, IO17=3, IO18=4),
    )
    sys.modules.setdefault("busio", types.SimpleNamespace(UART=DummyUART))

    spec = importlib.util.spec_from_file_location("bt_code_queue", code_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_nextion_queue_uses_deque_and_preserves_order():
    code = load_code_module()
    uart = DummyUART()
    nx = code.Nextion(uart, tx_interval_s=0, sendme_enabled=False)

    # Ensure we are using an efficient O(1) queue structure.
    assert nx.queue_is_deque

    # Enqueue a handful of commands and flush them through tick() calls.
    cmds = [f"cmd{i}" for i in range(5)]
    for c in cmds:
        nx.enqueue(c)

    for _ in cmds:
        nx.tick()

    sent = []
    for payload in uart.writes:
        assert payload.endswith(code.TERM)
        sent.append(payload[: -len(code.TERM)])
    assert sent == [c.encode("ascii") for c in cmds]

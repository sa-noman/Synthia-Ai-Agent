"""Agent Loop Guard - OpenJarvis architectural pattern adapted for Synthia.

Detects and prevents degenerate tool-calling loops:
1. Identical calls: Same tool called with identical parameters multiple times.
2. Ping-pong cycling: Repeated alternating tool calls (e.g. A-B-A-B or A-B-C-A-B-C).
3. Warn-before-block: Warns the model first so it can self-correct, then blocks.
"""
from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class LoopGuardConfig:
    enabled: bool = True
    max_identical_calls: int = 3
    ping_pong_window: int = 6
    warn_before_block: bool = True


@dataclass
class LoopVerdict:
    blocked: bool = False
    reason: str = ""
    warned: bool = False


class LoopGuard:
    def __init__(self, config: LoopGuardConfig | None = None) -> None:
        self.config = config or LoopGuardConfig()
        self._call_counts: dict[str, int] = {}
        self._tool_sequence: deque[str] = deque(maxlen=self.config.ping_pong_window * 2)
        self._warned_cycles: set[str] = set()

    def reset(self) -> None:
        self._call_counts.clear()
        self._tool_sequence.clear()
        self._warned_cycles.clear()

    def check_call(self, tool_name: str, arguments: Any) -> LoopVerdict:
        if not self.config.enabled:
            return LoopVerdict()

        args_str = str(arguments)
        call_hash = hashlib.sha256(f"{tool_name}:{args_str}".encode("utf-8")).hexdigest()[:16]
        self._call_counts[call_hash] = self._call_counts.get(call_hash, 0) + 1
        count = self._call_counts[call_hash]

        # 1. Identical call check
        if count >= self.config.max_identical_calls:
            reason = f"Repeated identical tool call '{tool_name}' ({count} times)."
            return self._decide(call_hash, reason)

        # 2. Ping-pong cycle check
        self._tool_sequence.append(tool_name)
        cycle_detected = self._detect_cycle()
        if cycle_detected:
            reason = f"Cyclic tool pattern detected: {cycle_detected}"
            return self._decide(cycle_detected, reason)

        return LoopVerdict()

    def _decide(self, cycle_key: str, reason: str) -> LoopVerdict:
        if self.config.warn_before_block and cycle_key not in self._warned_cycles:
            self._warned_cycles.add(cycle_key)
            return LoopVerdict(blocked=False, warned=True, reason=reason)
        return LoopVerdict(blocked=True, reason=reason)

    def _detect_cycle(self) -> str | None:
        seq = list(self._tool_sequence)
        n = len(seq)
        if n < 4:
            return None

        # Check for period 2: A-B-A-B
        if n >= 4 and seq[-1] == seq[-3] and seq[-2] == seq[-4] and seq[-1] != seq[-2]:
            return f"{seq[-2]} -> {seq[-1]} (ping-pong)"

        # Check for period 3: A-B-C-A-B-C
        if n >= 6 and seq[-1] == seq[-4] and seq[-2] == seq[-5] and seq[-3] == seq[-6]:
            return f"{seq[-3]} -> {seq[-2]} -> {seq[-1]} (3-step loop)"

        return None

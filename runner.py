"""Query execution with a spinner for ChainOps, ported from StealthOps'
runner.py. StealthOps' version also renders a banner and dispatches
enrichment providers; ChainOps doesn't have either concept yet, so this is
trimmed down to just the spinner wrapper.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, TypeVar

from formatter import _c, interactive_stdio

T = TypeVar("T")


def render_query_banner(target: str, use_color: bool = False) -> str:
    """"[ QUERY START ]" divider (StealthOps' console/CLI pattern) -- makes
    it easy to spot where each query begins when scrolling back through
    terminal output."""
    title = f"[ QUERY START ]  target={target}"
    border = "=" * max(64, len(title) + 6)
    if not use_color:
        return f"{border}\n{title}\n{border}"
    return f"{_c(True, border, '94')}\n{_c(True, title, '30;106')}\n{_c(True, border, '94')}"


def run_with_activity(label: str, fn: Callable[[], T]) -> T:
    if not interactive_stdio():
        return fn()
    stop = threading.Event()

    def spinner() -> None:
        glyphs = "|/-\\"
        idx = 0
        while not stop.wait(0.12):
            sys.stderr.write(f"\r[{glyphs[idx % len(glyphs)]}] {label}...")
            sys.stderr.flush()
            idx += 1
        clear_len = len(label) + 10
        sys.stderr.write("\r" + (" " * clear_len) + "\r")
        sys.stderr.flush()

    thread = threading.Thread(target=spinner, daemon=True)
    thread.start()
    try:
        return fn()
    finally:
        stop.set()
        thread.join(timeout=0.3)

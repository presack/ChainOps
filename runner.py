"""Query execution with a spinner for ChainOps, ported from StealthOps'
runner.py. StealthOps' version also renders a banner and dispatches
enrichment providers; ChainOps doesn't have either concept yet, so this is
trimmed down to just the spinner wrapper.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, TypeVar

from formatter import interactive_stdio

T = TypeVar("T")


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

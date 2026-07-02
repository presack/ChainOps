"""ChainOps interactive console — same interaction model as StealthOps:
query a seed, then `expand <address>`, `depth <n>`, accumulating a
session graph across commands.

Command handling lives on ConsoleSession so it's testable without
driving the actual input() loop; run_console() is just the thin REPL
shell around it.
"""

from __future__ import annotations

import os
from typing import Any

from core_ops import run_all_staged
from formatter import format_cli_report
from graph import DEFAULT_MAX_NEIGHBORS_PER_HOP, expand_neighbors

_GRAPH_DISPLAY_LIMIT = 25

HELP_TEXT = """
  Query
    <target>              run a lookup (BTC or Tron address; ETH parses but isn't queryable yet)
    expand [address]      expand neighbors from address (default: current seed) at the current depth
    depth <n>             set hop depth for subsequent expand commands (default: 1)

  Session
    graph                 show the accumulated session graph
    draw [path]            export the session graph as draw.io XML (default: ~/Downloads/chainops-map-<timestamp>.drawio)
    status                show seed, depth, and graph size
    reset                 clear the accumulated session graph
    clear                 clear the terminal
    help                  show this text
    exit / quit           leave the console
"""


class ConsoleSession:
    def __init__(self) -> None:
        self.seed: str | None = None
        self.depth: int = 1
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.truncated: bool = False
        self._seen_edge_keys: set[tuple[str, str, str]] = set()

    def merge_walk(self, walk: dict[str, Any]) -> None:
        for addr, info in walk.get("nodes", {}).items():
            existing = self.nodes.get(addr)
            if existing is None or info["depth"] < existing["depth"]:
                self.nodes[addr] = info
        for edge in walk.get("edges", []):
            key = (edge["txid"], edge["from"], edge["to"])
            if key not in self._seen_edge_keys:
                self._seen_edge_keys.add(key)
                self.edges.append(edge)
        if walk.get("truncated"):
            self.truncated = True

    def handle_query(self, target: str) -> str:
        result = run_all_staged(target)
        if result.get("target"):
            self.seed = result["target"]
        return format_cli_report(result)

    def handle_expand(self, address: str | None) -> str:
        target = address or self.seed
        if not target:
            return "error: no seed set - query a target first"

        walk = expand_neighbors(target, depth=self.depth)
        if not walk.get("valid") or walk.get("error"):
            return f"error: {walk.get('error', 'invalid target')}"

        new_nodes = sum(1 for addr in walk["nodes"] if addr not in self.nodes)
        new_edges = sum(
            1 for e in walk["edges"] if (e["txid"], e["from"], e["to"]) not in self._seen_edge_keys
        )
        self.merge_walk(walk)

        lines = [f"expanded {target} at depth {self.depth}: +{new_nodes} new node(s), +{new_edges} new edge(s)"]
        if walk.get("truncated"):
            lines.append(f"(truncated: hit the {DEFAULT_MAX_NEIGHBORS_PER_HOP}-neighbor-per-hop cap)")
        if walk.get("fetch_errors"):
            lines.append(f"({len(walk['fetch_errors'])} address(es) failed to fetch and were skipped)")
        lines.append(f"session graph now: {len(self.nodes)} node(s), {len(self.edges)} edge(s) total")
        return "\n".join(lines)

    def handle_depth(self, value: str) -> str:
        try:
            depth = int(value)
        except ValueError:
            return f"error: depth must be an integer, got '{value}'"
        if depth < 1:
            return "error: depth must be >= 1"
        self.depth = depth
        return f"depth set to {depth}"

    def handle_graph(self) -> str:
        if not self.nodes:
            return "session graph is empty - query a target or expand first"

        lines = [f"session graph: {len(self.nodes)} node(s), {len(self.edges)} edge(s)"]
        if self.truncated:
            lines.append("(one or more hops were truncated by the neighbor-per-hop cap)")

        ordered = sorted(self.nodes.items(), key=lambda kv: kv[1]["depth"])
        for addr, info in ordered[:_GRAPH_DISPLAY_LIMIT]:
            marker = " (seed)" if addr == self.seed else ""
            lines.append(f"  depth {info['depth']}: {addr}{marker}")
        if len(ordered) > _GRAPH_DISPLAY_LIMIT:
            lines.append(f"  ... and {len(ordered) - _GRAPH_DISPLAY_LIMIT} more")
        return "\n".join(lines)

    def handle_status(self) -> str:
        status = f"seed: {self.seed or '-'}\ndepth: {self.depth}\ngraph: {len(self.nodes)} node(s), {len(self.edges)} edge(s)"
        if self.truncated:
            status += " (truncated)"
        return status

    def handle_reset(self) -> str:
        self.nodes = {}
        self.edges = []
        self._seen_edge_keys = set()
        self.truncated = False
        return "session graph cleared"

    def handle_draw(self, out_path: str | None) -> str:
        if not self.nodes:
            return "session graph is empty - query a target or expand first"
        from draw import save_drawio_file

        saved_path = save_drawio_file(self.nodes, self.edges, seed=self.seed, out_path=out_path)
        return f"saved graph ({len(self.nodes)} node(s), {len(self.edges)} edge(s)) to {saved_path}"


def run_console() -> int:
    session = ConsoleSession()
    print("ChainOps console. Type 'help' for commands.")
    print("")

    while True:
        try:
            raw_in = input("chainops> ")
        except EOFError:
            print("")
            return 0
        except KeyboardInterrupt:
            print("")
            continue

        raw = raw_in.strip()
        if not raw:
            continue

        # Plain whitespace split, not shlex: shlex's backslash-escape
        # handling mangles Windows paths (e.g. in `draw C:\Users\...`).
        parts = raw.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in {"exit", "quit"}:
            return 0
        if cmd == "help":
            print(HELP_TEXT)
            continue
        if cmd == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue
        if cmd == "expand":
            print(session.handle_expand(args[0] if args else None))
            continue
        if cmd == "depth":
            print(session.handle_depth(args[0]) if args else f"depth is {session.depth}")
            continue
        if cmd == "graph":
            print(session.handle_graph())
            continue
        if cmd == "status":
            print(session.handle_status())
            continue
        if cmd == "reset":
            print(session.handle_reset())
            continue
        if cmd == "draw":
            print(session.handle_draw(args[0] if args else None))
            continue

        print(session.handle_query(raw))


if __name__ == "__main__":
    raise SystemExit(run_console())

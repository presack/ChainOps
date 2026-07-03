"""ChainOps interactive console — same interaction model as StealthOps:
query a seed, then `expand <address>`, `depth <n>`, accumulating a
session graph across commands.

Command handling lives on ConsoleSession so it's testable without
driving the actual input() loop; run_console() is just the thin REPL
shell around it.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from _version import __version__
from core_ops import run_all_staged
from formatter import _c, color_enabled, colorize_report, format_cli_report
from graph import DEFAULT_MAX_NEIGHBORS_PER_HOP, expand_neighbors
from runner import run_with_activity

_GRAPH_DISPLAY_LIMIT = 25

HELP_TEXT = """
  Query
    <target>              run a lookup (BTC, Tron, or ETH address, or an .eth ENS name)
    expand [address]      expand neighbors from address (default: current seed) at the current depth
    depth <n>             set hop depth for subsequent expand commands (default: 1)

    Example targets:
      1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a              BTC -- Silk Road-linked address (Forbes, 2013; public)
      TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t              Tron -- USDT (TRC20) contract address
      0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045      ETH -- vitalik.eth's address
      vitalik.eth                                     ENS name (resolves to the address above)

  Session
    graph                 show the accumulated session graph
    draw [path]            export the session graph as draw.io XML (default: ~/Downloads/chainops-map-<timestamp>.drawio)
    status                show seed, depth, and graph size
    reset                 clear the accumulated session graph
    clear                 clear the terminal

  Bulk triage
    bulk 1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a, 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
                                   inline list (comma or space separated; BTC addresses only for now)
    bulk /path/to/file.csv        read from a CSV (bare list, or a header row with an "address" column)
    bulk                          paste mode -- type addresses, blank line to submit

  Reports (PDF)
    report [path]                 PDF case report for the last query (default: ~/Downloads/chainops-<target>-<ts>.pdf)
    report cluster <id> [path]    PDF cluster report from the last 'bulk' run's triage rows

  Keys & providers
    providers              show which providers need a key and whether one's configured
    set-key                 interactive key setup wizard
    set-key evm <key>       set a key directly (evm = Etherscan/ETH, tron = TronGrid, optional)

  Other
    banner                redraw the startup banner
    version                show the current version
    update                check for and install an update (built binaries only)
    help                  show this text
    exit / quit           leave the console
"""

_ART_LINES = [
    "  ____ _           _        ___            ",
    " / ___| |__   __ _(_)_ __  / _ \\ _ __  ___ ",
    "| |   | '_ \\ / _` | | '_ \\| | | | '_ \\/ __|",
    "| |___| | | | (_| | | | | | |_| | |_) \\__ \\",
    " \\____|_| |_|\\__,_|_|_| |_|\\___/| .__/|___/",
    "                                |_|         ",
]


def render_console_banner(use_color: bool) -> str:
    title = _c(use_color, f"[ ON-CHAIN RECON & GRAPH INTELLIGENCE ]  v{__version__}", "92")
    rule = _c(use_color, "  _____________________________________________________________", "90")
    art = "\n".join(_c(use_color, line, "93") for line in _ART_LINES)

    etherscan_configured = bool(_etherscan_key())
    key_disp = _c(use_color, "Configured" if etherscan_configured else "Missing", "92" if etherscan_configured else "91")

    banner = (
        f"{art}\n"
        f"   {title}\n"
        "\n"
        f"  > ETHERSCAN_API_KEY ............... [{key_disp}]\n"
        f"{rule}"
    )
    from updater import get_update_notice
    notice = get_update_notice(use_color)
    if notice:
        banner += f"\n{notice}"
    return banner


def _etherscan_key() -> str:
    import keystore

    return keystore.get_key("ETHERSCAN_API_KEY")


def render_providers_status(use_color: bool) -> str:
    from enrichment.providers._registry import get_all_status

    lines = ["Provider key status:", ""]
    for status in get_all_status().values():
        spec = status["spec"]
        req = "required" if spec.required else "optional"
        if status["configured"]:
            state = _c(use_color, f"Configured ({status['masked']})", "92")
        else:
            state = _c(use_color, "Required, missing" if spec.required else "Missing (free tier used)", "91" if spec.required else "93")
        lines.append(f"  {spec.display_name:<24} [{spec.name}]  env={spec.env_var:<20} {req:<8} {state}")
    lines.append("")
    lines.append("Free, keyless: Bitcoin (Blockstream), price (CoinGecko), sanctions (OFAC SDN), wallet clustering (WalletExplorer, BTC only)")
    lines.append("Use 'set-key' to configure keys interactively, or 'set-key <provider> <key>' directly.")
    return "\n".join(lines)


def _default_bulk_csv_path() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    downloads = Path.home() / "Downloads"
    base_dir = downloads if downloads.is_dir() else Path.home()
    return str(base_dir / f"chainops-bulk-{ts}.csv")


class ConsoleSession:
    def __init__(self) -> None:
        self.seed: str | None = None
        self.depth: int = 1
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.truncated: bool = False
        self._seen_edge_keys: set[tuple[str, str, str]] = set()
        self.last_result: dict[str, Any] | None = None
        self.last_triage_rows: list[dict[str, Any]] | None = None

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

    def handle_query(self, target: str, use_color: bool = False) -> str:
        result = run_with_activity("Gathering results", lambda: run_all_staged(target))
        self.last_result = result
        if result.get("target"):
            self.seed = result["target"]
        return colorize_report(format_cli_report(result), use_color)

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
            if info.get("is_contract"):
                marker += " [contract]"
            if info.get("sanctioned"):
                marker += " [!] SANCTIONED"
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

    def handle_bulk_inline(self, addresses: list[str]) -> str:
        if not addresses:
            return "error: no addresses given"
        from bulk import triage_addresses, write_triage_csv

        rows = run_with_activity(f"Triaging {len(addresses)} address(es)", lambda: triage_addresses(addresses))
        self.last_triage_rows = rows
        out_path = _default_bulk_csv_path()
        write_triage_csv(rows, out_path)

        sanctioned = sum(1 for r in rows if r.get("sanctions_hit") is True)
        errored = sum(1 for r in rows if r.get("error"))
        lines = [f"triaged {len(rows)} address(es), saved to {out_path}"]
        if sanctioned:
            lines.append(f"[!] {sanctioned} address(es) matched the OFAC SDN list")
        if errored:
            lines.append(f"({errored} address(es) failed to fetch)")
        return "\n".join(lines)

    def handle_bulk_file(self, path: str) -> str:
        from bulk import read_addresses_csv

        try:
            addresses = read_addresses_csv(path)
        except OSError as exc:
            return f"error: could not read {path}: {exc}"
        if not addresses:
            return f"error: no addresses found in {path}"
        return self.handle_bulk_inline(addresses)

    def handle_report(self, out_path: str | None) -> str:
        if not self.last_result:
            return "error: no query result yet - query a target first"
        from report import generate_address_report

        target = self.last_result.get("target") or self.seed or "unknown"
        try:
            dest = generate_address_report(target, self.last_result, out_path)
        except RuntimeError as exc:
            return f"error: {exc}"
        return f"saved report to {dest}"

    def handle_report_cluster(self, cluster_id: str, out_path: str | None) -> str:
        if not self.last_triage_rows:
            return "error: no bulk triage results yet - run 'bulk' first"
        rows = [row for row in self.last_triage_rows if row.get("cluster_id") == cluster_id]
        if not rows:
            return f"error: no rows found with cluster_id '{cluster_id}'"
        from report import generate_cluster_report

        try:
            dest = generate_cluster_report(cluster_id, rows, out_path)
        except RuntimeError as exc:
            return f"error: {exc}"
        return f"saved cluster report ({len(rows)} member(s)) to {dest}"


def run_console() -> int:
    from updater import check_for_update_background, cleanup_old_binary

    cleanup_old_binary()
    check_for_update_background()

    session = ConsoleSession()
    use_color = color_enabled(no_color=False)
    os.system("cls" if os.name == "nt" else "clear")
    print(render_console_banner(use_color))
    print("")
    print("Type 'help' for commands.")
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
        if cmd == "bulk":
            if not args:
                print("Paste addresses (one or more per line), blank line to submit:")
                pasted: list[str] = []
                while True:
                    try:
                        line = input()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if not line.strip():
                        break
                    pasted.extend(part.strip(",") for part in line.replace(",", " ").split() if part.strip(","))
                print(session.handle_bulk_inline(pasted))
            elif len(args) == 1 and os.path.isfile(args[0]):
                print(session.handle_bulk_file(args[0]))
            else:
                addresses = [part.strip(",") for part in raw[len(cmd):].replace(",", " ").split() if part.strip(",")]
                print(session.handle_bulk_inline(addresses))
            continue
        if cmd == "report":
            if args and args[0].lower() == "cluster":
                if len(args) < 2:
                    print("error: usage: report cluster <cluster_id> [path]")
                else:
                    print(session.handle_report_cluster(args[1], args[2] if len(args) > 2 else None))
            else:
                print(session.handle_report(args[0] if args else None))
            continue
        if cmd == "providers":
            print(render_providers_status(use_color))
            continue
        if cmd == "set-key":
            import keystore
            from enrichment.providers._registry import KEY_PROVIDERS, get_key_status

            if not args:
                keystore.run_setup_wizard()
            elif args[0] not in KEY_PROVIDERS:
                print(f"error: unknown provider '{args[0]}' -- choices: {', '.join(KEY_PROVIDERS)}")
            elif len(args) == 1:
                spec = KEY_PROVIDERS[args[0]]
                status = get_key_status(args[0])
                suffix = f" [{status['masked']}]" if status["configured"] else " [not set]"
                try:
                    new_val = input(f"  {spec.display_name}{suffix}: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("")
                    new_val = ""
                if new_val:
                    keystore.set_key(spec.env_var, new_val)
                    print("  [saved]")
                else:
                    print("  no change")
            else:
                spec = KEY_PROVIDERS[args[0]]
                keystore.set_key(spec.env_var, " ".join(args[1:]))
                print(f"  {spec.display_name} key saved")
            continue
        if cmd == "banner":
            print(render_console_banner(use_color))
            continue
        if cmd == "version":
            print(f"ChainOps {__version__}")
            continue
        if cmd == "update":
            from updater import do_update

            try:
                new_tag = do_update(use_color)
            except KeyboardInterrupt:
                print("\ninterrupted")
                continue
            if new_tag:
                try:
                    ans = input(f"  Restart now to use {new_tag}? [y/N] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    ans = ""
                if ans == "y":
                    import sys as _sys
                    os.execv(_sys.executable, _sys.argv)
            continue

        print(session.handle_query(raw, use_color))


if __name__ == "__main__":
    raise SystemExit(run_console())

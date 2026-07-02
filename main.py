"""ChainOps entrypoint (CLI single-shot; console mode; web mode lands in a later phase)."""

from __future__ import annotations

import argparse
import json

from core_ops import run_all_staged
from formatter import format_cli_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ChainOps - blockchain address/tx recon utility")
    parser.add_argument("target", nargs="?", help="BTC/ETH/Tron address, txid, block height, or ENS name")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of a formatted report")
    parser.add_argument("--console", action="store_true", help="Start the interactive console (REPL)")
    return parser.parse_args()


def run_cli(target: str, as_json: bool) -> int:
    result = run_all_staged(target)
    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_cli_report(result))
    return 0 if result.get("valid") and "error" not in result else 1


def main() -> int:
    args = parse_args()

    if args.console:
        from console import run_console

        return run_console()

    if not args.target:
        print("error: target is required unless --console is given")
        return 1

    return run_cli(args.target, args.json)


if __name__ == "__main__":
    raise SystemExit(main())

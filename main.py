"""ChainOps entrypoint (CLI single-shot; console mode; web mode)."""

from __future__ import annotations

import argparse
import json

from _version import __version__
from core_ops import run_all_staged
from formatter import color_enabled, colorize_report, format_cli_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ChainOps - blockchain address/tx recon utility")
    parser.add_argument("--version", action="version", version=f"ChainOps {__version__}")
    parser.add_argument("target", nargs="?", help="BTC/ETH/Tron address, txid, block height, or ENS name")

    exec_grp = parser.add_argument_group("execution mode")
    exec_grp.add_argument("--console", action="store_true", help="Start the interactive console (REPL)")
    exec_grp.add_argument("--web", action="store_true", help="Start the web UI")
    exec_grp.add_argument("--update", action="store_true", help="Check for and install an update (built binaries only)")

    query_grp = parser.add_argument_group("query options")
    query_grp.add_argument("--json", action="store_true", help="Output raw JSON instead of a formatted report")
    query_grp.add_argument("--no-color", action="store_true", help="Disable colored output")

    keys_grp = parser.add_argument_group("key management")
    keys_grp.add_argument("--configure-keys", action="store_true", help="Interactive API key setup wizard")
    keys_grp.add_argument("--providers", action="store_true", help="Show provider key status (configured/missing)")

    web_grp = parser.add_argument_group("web server")
    web_grp.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    web_grp.add_argument("--port", type=int, default=5000, help="Bind port (default: 5000)")

    return parser.parse_args()


def run_web(host: str, port: int) -> int:
    import uvicorn

    from web_ui import build_app

    uvicorn.run(build_app(), host=host, port=port)
    return 0


def run_cli(target: str, as_json: bool, use_color: bool = False) -> int:
    from runner import run_with_activity

    result = run_with_activity("Gathering results", lambda: run_all_staged(target))
    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(colorize_report(format_cli_report(result), use_color))
    return 0 if result.get("valid") and "error" not in result else 1


def main() -> int:
    args = parse_args()
    use_color = color_enabled(args.no_color)

    from keystore import load_into_environ
    from updater import check_for_update_background, cleanup_old_binary

    load_into_environ()
    cleanup_old_binary()
    check_for_update_background()

    if args.update:
        from updater import do_update

        do_update(use_color=use_color)
        return 0

    if args.configure_keys:
        from keystore import run_setup_wizard

        run_setup_wizard()
        return 0

    if args.providers:
        from console import render_providers_status

        print(render_providers_status(use_color))
        return 0

    if args.console:
        from console import run_console

        return run_console()

    if args.web:
        return run_web(args.host, args.port)

    if not args.target:
        print("error: target is required unless --console is given")
        return 1

    return run_cli(args.target, args.json, use_color)


if __name__ == "__main__":
    raise SystemExit(main())

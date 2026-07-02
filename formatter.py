"""CLI report formatting for ChainOps, StealthOps-style: "=== SECTION ===
[source: ...]" blocks of "Label: value" lines.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _fmt_ts(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return value
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_cli_report(result: dict[str, Any]) -> str:
    lines: list[str] = []

    lines.append("=== TARGET ===  [source: classify_target]")
    lines.append(f"Target: {result.get('target', '-')}")
    lines.append(f"Chain: {result.get('chain', '-')}")
    lines.append(f"Type: {result.get('target_type', '-')}")
    if not result.get("valid"):
        lines.append(f"Error: {result.get('error', 'invalid target')}")
        return "\n".join(lines)
    if result.get("error"):
        lines.append(f"Error: {result['error']}")
        return "\n".join(lines)

    chain = result.get("chain")
    native_balance = 0.0

    if chain == "tron":
        tron = result.get("tron", {})
        lines.append("")
        lines.append("=== BALANCE ===  [source: TronGrid API]")
        if "error" in tron:
            lines.append(f"Error: {tron['error']}")
        else:
            native_balance = tron.get("balance_trx", 0)
            lines.append(f"Balance: {native_balance:.6f} TRX" + ("" if tron.get("activated") else " (unactivated address)"))
            lines.append(f"USDT (TRC20) transfers seen: {tron.get('usdt_transfer_count', '-')}")

        lines.append("")
        lines.append("=== ACTIVITY ===  [source: TronGrid full USDT transfer history]")
        if "tx_history_error" in result:
            lines.append(f"Error: {result['tx_history_error']}")
        elif "first_seen" in result:
            lines.append(f"First seen: {_fmt_ts(result.get('first_seen'))}")
            lines.append(f"Last seen: {_fmt_ts(result.get('last_seen'))}")
            dormancy = result.get("dormancy_days")
            lines.append(f"Dormancy: {dormancy} days" if dormancy is not None else "Dormancy: -")
        else:
            lines.append("- not available")
    else:
        blockstream = result.get("blockstream", {})
        lines.append("")
        lines.append("=== BALANCE / UTXO ===  [source: Blockstream Esplora API]")
        if "error" in blockstream:
            lines.append(f"Error: {blockstream['error']}")
        else:
            native_balance = blockstream.get("balance_btc", 0)
            lines.append(f"Balance: {native_balance:.8f} BTC ({blockstream.get('balance_sats', 0)} sats)")
            unconfirmed = blockstream.get("unconfirmed_balance_sats", 0)
            if unconfirmed:
                lines.append(f"Unconfirmed: {unconfirmed} sats")
            lines.append(f"Tx count: {blockstream.get('tx_count', '-')}")
            lines.append(f"UTXO count: {blockstream.get('utxo_count', '-')}")

        lines.append("")
        lines.append("=== ACTIVITY ===  [source: Blockstream full tx history]")
        if "tx_history_error" in result:
            lines.append(f"Error: {result['tx_history_error']}")
        elif "first_seen" in result:
            lines.append(f"First seen: {_fmt_ts(result.get('first_seen'))}")
            lines.append(f"Last seen: {_fmt_ts(result.get('last_seen'))}")
            dormancy = result.get("dormancy_days")
            lines.append(f"Dormancy: {dormancy} days" if dormancy is not None else "Dormancy: -")
        else:
            lines.append("- not available")

    price = result.get("price", {})
    lines.append("")
    lines.append("=== PRICE ===  [source: CoinGecko]")
    if "error" in price:
        lines.append(f"Error: {price['error']}")
    else:
        usd = price.get("usd")
        lines.append(f"Current price: ${usd:,}" if usd is not None else "Current price: -")
        if usd is not None and "error" not in result.get("blockstream" if chain != "tron" else "tron", {}):
            value_usd = native_balance * usd
            lines.append(f"Balance value: ${value_usd:,.2f}")

    if chain != "tron":
        walletexplorer = result.get("walletexplorer", {})
        lines.append("")
        lines.append("=== WALLET CLUSTERING ===  [source: WalletExplorer.com]")
        if "error" in walletexplorer:
            lines.append(f"Error: {walletexplorer['error']}")
        elif not walletexplorer.get("found"):
            lines.append("No cluster match (coverage is stale/pre-2018-biased)")
        else:
            lines.append(f"Wallet ID: {walletexplorer.get('wallet_id', '-')}")
            if walletexplorer.get("label"):
                lines.append(f"Label: {walletexplorer['label']}")

    ofac = result.get("ofac_sdn", {})
    lines.append("")
    lines.append("=== SANCTIONS ===  [source: OFAC SDN list]")
    if not ofac.get("checked", False):
        lines.append(f"Error: {ofac.get('error', 'unavailable')}")
    elif ofac.get("sanctioned"):
        lines.append("[!] SANCTIONED MATCH — this address appears on the OFAC SDN list")
    else:
        lines.append("No match")

    return "\n".join(lines)

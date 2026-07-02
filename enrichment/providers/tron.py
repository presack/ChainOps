"""TronGrid API adapter — Tron address balance + USDT (TRC20) transfer history.

Free, no API key required (rate-limited without one); pass a TronGrid key
via `key` to raise the limit. Address-only for now, mirroring blockstream.py.
"""

from __future__ import annotations

from typing import Any

import requests

from core_ops import Chain
from enrichment.providers._shared import ENRICHMENT_TIMEOUT_SECONDS, error_result, require_chain, short_http_error

_API_ROOT = "https://api.trongrid.io"
_SUN_PER_TRX = 1_000_000
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def _get(path: str, key: str, params: dict[str, Any] | None = None) -> requests.Response:
    headers = {"TRON-PRO-API-KEY": key} if key else {}
    return requests.get(f"{_API_ROOT}{path}", headers=headers, params=params, timeout=ENRICHMENT_TIMEOUT_SECONDS)


def run(target: str, key: str) -> dict[str, Any]:
    classified = require_chain(target, Chain.TRON, "tron")
    if isinstance(classified, dict):
        return classified

    address = classified.target

    account_resp = _get(f"/v1/accounts/{address}", key)
    if account_resp.status_code >= 400:
        return error_result("tron", short_http_error(account_resp))
    account_data = account_resp.json().get("data", [])
    account = account_data[0] if account_data else {}

    balance_sun = account.get("balance", 0)
    trc20_balances = {contract: amount for entry in account.get("trc20", []) for contract, amount in entry.items()}

    transfers_resp = _get(
        f"/v1/accounts/{address}/transactions/trc20",
        key,
        params={"limit": 50, "contract_address": USDT_CONTRACT},
    )
    if transfers_resp.status_code >= 400:
        return error_result("tron", short_http_error(transfers_resp))
    usdt_transfers = [_format_transfer(t) for t in transfers_resp.json().get("data", [])]

    return {
        "source": "tron",
        "chain": Chain.TRON,
        "address": address,
        "activated": bool(account_data),
        "balance_sun": balance_sun,
        "balance_trx": balance_sun / _SUN_PER_TRX,
        "trc20_balances": trc20_balances,
        "usdt_transfer_count": len(usdt_transfers),
        "recent_usdt_transfers": usdt_transfers,
    }


def _format_transfer(transfer: dict[str, Any]) -> dict[str, Any]:
    token = transfer.get("token_info", {})
    decimals = token.get("decimals", 6)
    try:
        amount = int(transfer.get("value", "0")) / (10**decimals)
    except (TypeError, ValueError):
        amount = None
    return {
        "txid": transfer.get("transaction_id"),
        "from": transfer.get("from"),
        "to": transfer.get("to"),
        "amount": amount,
        "symbol": token.get("symbol"),
        "block_timestamp": transfer.get("block_timestamp"),
    }


def summary(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"tron error={payload['error']}"
    return f"tron balance={payload['balance_trx']:.6f} TRX usdt_transfers={payload['usdt_transfer_count']}"

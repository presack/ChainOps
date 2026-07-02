"""Etherscan V2 API adapter — ETH balance, normal tx list, ERC20 transfers.

Etherscan's V2 API unifies what used to be separate per-chain APIs
(Etherscan/BscScan/Polygonscan) behind one endpoint + a `chainid` param,
replacing the old "same API shape, different base URL" model (Etherscan's
V1 endpoints are deprecated -- verified live 2026-07-02, a V1 call now
returns an explicit "switch to Etherscan API V2" error). This adapter
only targets chainid=1 (Ethereum mainnet) for now, since that's the only
EVM chain core_ops.classify_target() currently recognizes; adding BSC/
Polygon later is a matter of passing a different chainid, not a new
adapter.

Unlike Blockstream/TronGrid, Etherscan serves *no* traffic without a key
(verified live 2026-07-02: an unauthenticated balance lookup returns
"Missing/Invalid API Key"), so `run()` requires `key` and returns an
error_result immediately if it's empty -- no free/keyless path exists.

NOT YET LIVE-VERIFIED (2026-07-02): building this against Etherscan's
documented V2 API shape without an API key on hand. Covered by mocked
tests only; run it against a real ETHERSCAN_API_KEY before relying on it.
"""

from __future__ import annotations

from typing import Any

import requests

from core_ops import Chain, TargetType
from enrichment.providers._shared import ENRICHMENT_TIMEOUT_SECONDS, error_result, require_chain

_API_ROOT = "https://api.etherscan.io/v2/api"
_CHAIN_ID = 1  # Ethereum mainnet
_WEI_PER_ETH = 10**18

_EMPTY_RESULT_MESSAGES = {"no transactions found", "no token transfers found"}


def _get(params: dict[str, Any], key: str) -> requests.Response:
    return requests.get(
        _API_ROOT,
        params={**params, "chainid": _CHAIN_ID, "apikey": key},
        timeout=ENRICHMENT_TIMEOUT_SECONDS,
    )


def _call(action: str, params: dict[str, Any], key: str) -> tuple[Any, str | None]:
    """Make an Etherscan V2 call and return (result, error).

    Etherscan reports both real errors and legitimate "no data found"
    results as HTTP 200 with status="0" -- only the former is an error,
    so this distinguishes them by message rather than treating every
    status="0" as a failure.
    """
    try:
        response = _get({"module": "account", "action": action, **params}, key)
    except requests.RequestException as exc:
        return None, f"request failed: {exc}"

    if response.status_code >= 400:
        return None, f"http {response.status_code}"

    body = response.json()
    status = body.get("status")
    message = str(body.get("message", ""))
    result = body.get("result")

    if status == "1":
        return result, None
    if _is_empty_result(message):
        return result if result is not None else [], None
    return None, message or "unknown error"


def _is_empty_result(message: str) -> bool:
    return message.strip().lower() in _EMPTY_RESULT_MESSAGES


def run(target: str, key: str) -> dict[str, Any]:
    classified = require_chain(target, Chain.ETHEREUM, "evm")
    if isinstance(classified, dict):
        return classified
    if classified.target_type != TargetType.ETH_ADDRESS:
        return error_result(
            "evm",
            f"evm requires a resolved ETH address (got {classified.target_type}); "
            "ENS names need resolving to an address first",
            classified.target_type,
        )
    if not key:
        return error_result("evm", "ETHERSCAN_API_KEY required (Etherscan serves no unauthenticated traffic)")

    address = classified.target

    balance_result, balance_error = _call("balance", {"address": address, "tag": "latest"}, key)
    if balance_error:
        return error_result("evm", balance_error)
    balance_wei = int(balance_result)

    txlist_result, txlist_error = _call(
        "txlist",
        {"address": address, "startblock": 0, "endblock": 99999999, "page": 1, "offset": 50, "sort": "desc"},
        key,
    )
    if txlist_error:
        return error_result("evm", txlist_error)

    tokentx_result, tokentx_error = _call(
        "tokentx",
        {"address": address, "page": 1, "offset": 50, "sort": "desc"},
        key,
    )
    if tokentx_error:
        return error_result("evm", tokentx_error)

    last_seen = None
    if txlist_result:
        last_seen = int(txlist_result[0]["timeStamp"])

    return {
        "source": "evm",
        "chain": Chain.ETHEREUM,
        "address": address,
        "balance_wei": balance_wei,
        "balance_eth": balance_wei / _WEI_PER_ETH,
        "tx_count": len(txlist_result),
        "recent_txs": [tx.get("hash") for tx in txlist_result],
        "token_transfer_count": len(tokentx_result),
        "recent_token_transfers": [_format_token_transfer(t) for t in tokentx_result],
        "last_seen": last_seen,
    }


def _format_token_transfer(transfer: dict[str, Any]) -> dict[str, Any]:
    decimals_raw = transfer.get("tokenDecimal", "18")
    try:
        decimals = int(decimals_raw)
        amount = int(transfer.get("value", "0")) / (10**decimals)
    except (TypeError, ValueError):
        amount = None
    return {
        "txid": transfer.get("hash"),
        "from": transfer.get("from"),
        "to": transfer.get("to"),
        "amount": amount,
        "symbol": transfer.get("tokenSymbol"),
        "contract": transfer.get("contractAddress"),
        "timestamp": int(transfer["timeStamp"]) if transfer.get("timeStamp") else None,
    }


def summary(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"evm error={payload['error']}"
    return (
        f"evm balance={payload['balance_eth']:.6f} ETH "
        f"tx_count={payload['tx_count']} token_transfers={payload['token_transfer_count']}"
    )

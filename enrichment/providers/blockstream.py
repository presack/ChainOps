"""Blockstream Esplora API adapter — BTC address balance, UTXO set, tx list.

Free, no API key required. Address-only for now (txid/block-height
lookups are a separate concern once the graph-walk engine needs them).
"""

from __future__ import annotations

from typing import Any

import requests

from core_ops import BTC_ADDRESS_TYPES, Chain
from enrichment.providers._shared import ENRICHMENT_TIMEOUT_SECONDS, error_result, require_chain, short_http_error

_API_ROOT = "https://blockstream.info/api"


def _get(path: str) -> requests.Response:
    return requests.get(f"{_API_ROOT}{path}", timeout=ENRICHMENT_TIMEOUT_SECONDS)


def run(target: str, key: str) -> dict[str, Any]:
    classified = require_chain(target, Chain.BITCOIN, "blockstream")
    if isinstance(classified, dict):
        return classified
    if classified.target_type not in BTC_ADDRESS_TYPES:
        return error_result(
            "blockstream",
            f"blockstream requires a BTC address target, got {classified.target_type}",
            classified.target_type,
        )

    address = classified.target

    try:
        stats_resp = _get(f"/address/{address}")
        if stats_resp.status_code >= 400:
            return error_result("blockstream", short_http_error(stats_resp))
        stats = stats_resp.json()

        utxo_resp = _get(f"/address/{address}/utxo")
        if utxo_resp.status_code >= 400:
            return error_result("blockstream", short_http_error(utxo_resp))
        utxos = utxo_resp.json()

        txs_resp = _get(f"/address/{address}/txs")
        if txs_resp.status_code >= 400:
            return error_result("blockstream", short_http_error(txs_resp))
        txs = txs_resp.json()
    except requests.exceptions.RequestException as exc:
        return error_result("blockstream", f"network error: {exc}")

    chain_stats = stats.get("chain_stats", {})
    mempool_stats = stats.get("mempool_stats", {})

    confirmed_balance_sats = chain_stats.get("funded_txo_sum", 0) - chain_stats.get("spent_txo_sum", 0)
    unconfirmed_balance_sats = mempool_stats.get("funded_txo_sum", 0) - mempool_stats.get("spent_txo_sum", 0)

    last_seen = None
    if txs:
        newest = txs[0]
        status = newest.get("status", {})
        last_seen = status.get("block_time") if status.get("confirmed") else "unconfirmed"

    return {
        "source": "blockstream",
        "chain": Chain.BITCOIN,
        "address": address,
        "balance_sats": confirmed_balance_sats,
        "balance_btc": confirmed_balance_sats / 1e8,
        "unconfirmed_balance_sats": unconfirmed_balance_sats,
        "tx_count": chain_stats.get("tx_count", 0) + mempool_stats.get("tx_count", 0),
        "utxo_count": len(utxos),
        "utxos": utxos,
        "recent_txs": [tx.get("txid") for tx in txs],
        "last_seen": last_seen,
    }


def summary(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"blockstream error={payload['error']}"
    return (
        f"blockstream balance={payload['balance_btc']:.8f} BTC "
        f"tx_count={payload['tx_count']} utxos={payload['utxo_count']}"
    )


def fetch_tx_history(address: str, max_pages: int = 50) -> list[dict[str, Any]]:
    """Full confirmed+mempool tx history via pagination (25 confirmed txs
    per page after the first). Not part of the run()/summary() contract —
    a high-activity address can take many requests, so this is a separate,
    directly-callable function for core_ops.run_all_staged() to compute
    first/last-seen and dormancy. Raises on HTTP failure; callers should
    catch and degrade gracefully rather than treat this as optional.
    """
    page = _get(f"/address/{address}/txs")
    page.raise_for_status()
    latest_page: list[dict[str, Any]] = page.json()
    all_txs: list[dict[str, Any]] = list(latest_page)

    pages_fetched = 1
    while len(latest_page) == 25 and pages_fetched < max_pages:
        last_txid = latest_page[-1]["txid"]
        next_page = _get(f"/address/{address}/txs/chain/{last_txid}")
        next_page.raise_for_status()
        latest_page = next_page.json()
        if not latest_page:
            break
        all_txs.extend(latest_page)
        pages_fetched += 1

    return all_txs


def fetch_recent_txs(address: str) -> list[dict[str, Any]]:
    """First page only (up to 25 confirmed + mempool), full tx objects
    including vin/vout/prevout addresses. Used by the graph-walk engine
    instead of fetch_tx_history(): a multi-hop walk fans out to many
    addresses, and paginating each one's full history would multiply
    request counts unpredictably for high-degree hub addresses (exchanges,
    mixers). Raises on HTTP failure.
    """
    response = _get(f"/address/{address}/txs")
    response.raise_for_status()
    return response.json()

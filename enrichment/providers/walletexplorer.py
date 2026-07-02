"""WalletExplorer.com adapter — free common-input-ownership wallet clustering
and (when available) a human label for the cluster.

Verified live 2026-07-02: the JSON lookup API returns found/wallet_id but
no label field. Labels only exist for wallet_id if the wallet page's
wallet_name element has been set to something other than the default
"[<10-hex-char prefix>]" placeholder -- most clusters never get one.
Matches the roadmap's own caveat: coverage is stale/pre-2018-biased, but
free and worth surfacing when present.
"""

from __future__ import annotations

import re
from typing import Any

import requests

from core_ops import BTC_ADDRESS_TYPES, Chain
from enrichment.providers._shared import ENRICHMENT_TIMEOUT_SECONDS, error_result, require_chain, short_http_error

_LOOKUP_URL = "https://www.walletexplorer.com/api/1/address-lookup"
_WALLET_PAGE_URL = "https://www.walletexplorer.com/wallet/{wallet_id}"
_CALLER = "chainops"

_PLACEHOLDER_LABEL_RE = re.compile(r"^\[[0-9a-f]{10}\]$")
_WALLET_NAME_RE = re.compile(r'wallet_name">([^<]*)')


def _fetch_wallet_label(wallet_id: str) -> str | None:
    """Best-effort scrape of the wallet page's display name. None if the
    page is unreachable or the wallet has no real label assigned."""
    try:
        response = requests.get(
            _WALLET_PAGE_URL.format(wallet_id=wallet_id), timeout=ENRICHMENT_TIMEOUT_SECONDS
        )
    except requests.RequestException:
        return None
    if response.status_code >= 400:
        return None
    match = _WALLET_NAME_RE.search(response.text)
    if not match:
        return None
    label = match.group(1).strip()
    if not label or _PLACEHOLDER_LABEL_RE.match(label):
        return None
    return label


def run(target: str, key: str) -> dict[str, Any]:
    classified = require_chain(target, Chain.BITCOIN, "walletexplorer")
    if isinstance(classified, dict):
        return classified
    if classified.target_type not in BTC_ADDRESS_TYPES:
        return error_result(
            "walletexplorer",
            f"walletexplorer requires a BTC address target, got {classified.target_type}",
            classified.target_type,
        )

    address = classified.target
    response = requests.get(
        _LOOKUP_URL, params={"address": address, "caller": _CALLER}, timeout=ENRICHMENT_TIMEOUT_SECONDS
    )
    if response.status_code >= 400:
        return error_result("walletexplorer", short_http_error(response))

    data = response.json()
    found = bool(data.get("found"))
    result: dict[str, Any] = {"source": "walletexplorer", "chain": Chain.BITCOIN, "address": address, "found": found}
    if not found:
        return result

    wallet_id = data.get("wallet_id")
    result["wallet_id"] = wallet_id
    label = _fetch_wallet_label(wallet_id) if wallet_id else None
    if label:
        result["label"] = label
    return result


def summary(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"walletexplorer error={payload['error']}"
    if not payload.get("found"):
        return "walletexplorer no cluster match (coverage is stale/pre-2018-biased)"
    label = payload.get("label")
    if label:
        return f"walletexplorer wallet={payload['wallet_id']} label={label}"
    return f"walletexplorer wallet={payload['wallet_id']} (no label on record)"

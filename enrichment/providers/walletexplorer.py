"""WalletExplorer.com adapter — free common-input-ownership wallet clustering,
a human label for the cluster when available, and known-service counterparties
found in the wallet's own transaction history.

Verified live 2026-07-15: the JSON lookup API does include a "label" field
for well-known/tagged wallets (e.g. exchange/service clusters) -- the
2026-07-02 note claiming it never does was wrong, just untested against a
labeled address. Most clusters still have no real label at all, so this
falls back to scraping the wallet page's wallet_name element (checking for
the default "[<10-hex-char prefix>]" placeholder) only when the lookup
response itself doesn't already carry one.

A wallet having no name of its own is not the same as having no useful
intel: WalletExplorer tags individual counterparties (e.g. "Bittrex.com",
"BTCGuild.com") directly in a wallet's transaction history even when the
wallet itself is unnamed -- this is often the more valuable signal (proof
of a real interaction with a known exchange/service) and was previously
invisible to ChainOps entirely. Pulled via the wallet page's CSV export
(`?format=csv&page=all`, confirmed live to actually return full history
in one request, unlike the plain HTML view which is paginated) since CSV
is far more reliably parseable than the nested per-transaction HTML tables.
"""

from __future__ import annotations

import csv
import io
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
_LABELED_COUNTERPARTY_RE = re.compile(r"^(.+) \(([0-9a-f]{16})\)$")


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


def _fetch_known_counterparties(wallet_id: str) -> list[dict[str, Any]] | None:
    """Best-effort fetch of the wallet's full transaction history (CSV export)
    and aggregation of any labeled (known-service) counterparties found in the
    "received from"/"sent to" columns. Returns None if the page is unreachable
    or unparseable; an empty list if reachable but no labeled counterparty
    appears (the common case for most wallets)."""
    try:
        response = requests.get(
            _WALLET_PAGE_URL.format(wallet_id=wallet_id),
            params={"format": "csv", "page": "all"},
            timeout=ENRICHMENT_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return None
    if response.status_code >= 400:
        return None

    # The leading metadata line is itself CSV-quoted (e.g. `"#Wallet ... "`),
    # so it starts with a literal quote, not "#" -- strip that before checking.
    lines = [line for line in response.text.splitlines() if not line.lstrip('"').startswith("#")]
    try:
        rows = list(csv.DictReader(lines))
    except csv.Error:
        return None

    aggregated: dict[str, dict[str, Any]] = {}
    for row in rows:
        for cell_field, amount_field in (("received from", "received amount"), ("sent to", "sent amount")):
            cell = (row.get(cell_field) or "").strip()
            date = (row.get("date") or "").strip()
            match = _LABELED_COUNTERPARTY_RE.match(cell)
            if not match or not date:
                continue
            label, cp_wallet_id = match.group(1), match.group(2)
            try:
                amount = float(row.get(amount_field) or 0)
            except ValueError:
                amount = 0.0

            entry = aggregated.setdefault(
                label,
                {
                    "label": label,
                    "wallet_id": cp_wallet_id,
                    "count": 0,
                    "total_btc": 0.0,
                    "first_seen": date,
                    "last_seen": date,
                },
            )
            entry["count"] += 1
            entry["total_btc"] += amount
            entry["first_seen"] = min(entry["first_seen"], date)
            entry["last_seen"] = max(entry["last_seen"], date)

    return sorted(aggregated.values(), key=lambda e: e["count"], reverse=True)


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
    try:
        response = requests.get(
            _LOOKUP_URL, params={"address": address, "caller": _CALLER}, timeout=ENRICHMENT_TIMEOUT_SECONDS
        )
    except requests.exceptions.RequestException as exc:
        return error_result("walletexplorer", f"network error: {exc}")
    if response.status_code >= 400:
        return error_result("walletexplorer", short_http_error(response))

    data = response.json()
    found = bool(data.get("found"))
    result: dict[str, Any] = {"source": "walletexplorer", "chain": Chain.BITCOIN, "address": address, "found": found}
    if not found:
        return result

    wallet_id = data.get("wallet_id")
    result["wallet_id"] = wallet_id
    label = data.get("label") or (_fetch_wallet_label(wallet_id) if wallet_id else None)
    if label:
        result["label"] = label

    known_counterparties = _fetch_known_counterparties(wallet_id) if wallet_id else None
    if known_counterparties:
        result["known_counterparties"] = known_counterparties
    return result


def summary(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"walletexplorer error={payload['error']}"
    if not payload.get("found"):
        return "walletexplorer no cluster match (coverage is stale/pre-2018-biased)"
    label = payload.get("label")
    base = f"walletexplorer wallet={payload['wallet_id']} label={label}" if label else \
        f"walletexplorer wallet={payload['wallet_id']} (no label on record)"
    known_counterparties = payload.get("known_counterparties")
    if known_counterparties:
        base += f", {len(known_counterparties)} known counterpart{'y' if len(known_counterparties) == 1 else 'ies'} in history"
    return base

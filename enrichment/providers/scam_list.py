"""Community scam-address blocklist -- flags exact matches against
ScamSniffer's crowdsourced/community-reported scam address list.

ROADMAP originally named Chainabuse and CryptoScamDB for "community
scam/abuse lists," but neither is usable as a free API (both confirmed
live 2026-07-02): Chainabuse has no public REST endpoint (`/api` 404s --
it's web-UI-only, likely intentionally not exposed for scripted access),
and CryptoScamDB's API (`api.cryptoscamdb.org`) returns a hard 502,
consistently across retries, not a transient blip -- the service appears
to be down. ScamSniffer's GitHub-hosted blocklist
(github.com/scamsniffer/scam-database) is free, no key, actively
maintained (pushed within 24h of that same check), and -- unlike
MetaMask's eth-phishing-detect list, which is domain-only -- is
address-level, matching ChainOps' address-centric model.

EVM-only: the list is exclusively "0x..." addresses (2,530 entries,
confirmed live). No equivalent Tron/BTC community scam-address list was
found; this is a real, documented gap, not silently pretended-away.

Same cache-once, explicit-refresh pattern as ofac_sdn.py -- the list is
~10MB combined (smaller for address.json alone), not worth re-downloading
on every query.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

from core_ops import Chain, classify_target
from enrichment.providers._shared import error_result

_BLOCKLIST_URL = "https://raw.githubusercontent.com/scamsniffer/scam-database/main/blacklist/address.json"
_DOWNLOAD_TIMEOUT_SECONDS = 30


def _cache_path() -> str:
    return os.environ.get("SCAM_LIST_CACHE_PATH", os.path.join("cache", "scam_list_addresses.json"))


def download_addresses() -> list[str]:
    response = requests.get(_BLOCKLIST_URL, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def refresh() -> dict[str, Any]:
    """Force a fresh download + on-disk cache write."""
    addresses = download_addresses()
    payload = {"downloaded_at": int(time.time()), "addresses": addresses}

    path = _cache_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)
    return payload


def _load_cache() -> dict[str, Any] | None:
    try:
        with open(_cache_path()) as f:
            return json.load(f)
    except Exception:
        return None


def load_addresses() -> dict[str, Any]:
    """Return cached blocklist data, downloading once if no cache exists.

    Does not re-download just because the cache is old -- call refresh()
    explicitly to pick up list updates, same as ofac_sdn.load_addresses().
    """
    cached = _load_cache()
    if cached is not None:
        return cached
    return refresh()


def check_addresses(addresses: list[str], chain: str) -> dict[str, bool]:
    """Batch-check many addresses in a single cache load. EVM-only -- any
    other chain reports every address as not-flagged rather than raising,
    since a walk/report shouldn't fail outright over an unsupported chain.
    Used by graph.py to flag scam-listed nodes discovered during a walk.
    """
    if chain != Chain.ETHEREUM:
        return {addr: False for addr in addresses}

    try:
        cache_data = load_addresses()
    except Exception:
        return {addr: False for addr in addresses}

    scam_addresses = {a.lower() for a in cache_data.get("addresses", [])}
    return {addr: addr.lower() in scam_addresses for addr in addresses}


def run(target: str, key: str) -> dict[str, Any]:
    classified = classify_target(target)
    if not classified.valid:
        return error_result("scam_list", f"unrecognized target: {classified.detail}", classified.target_type)
    if classified.chain != Chain.ETHEREUM:
        return {
            "source": "scam_list",
            "chain": classified.chain,
            "address": classified.target,
            "checked": False,
            "error": f"no community scam-address list available for chain {classified.chain} (EVM only)",
        }

    try:
        cache_data = load_addresses()
    except Exception as exc:
        return {
            "source": "scam_list",
            "chain": classified.chain,
            "address": classified.target,
            "checked": False,
            "error": f"scam address list unavailable: {exc}",
        }

    scam_addresses = {a.lower() for a in cache_data.get("addresses", [])}
    flagged = classified.target.lower() in scam_addresses

    return {
        "source": "scam_list",
        "chain": classified.chain,
        "address": classified.target,
        "checked": True,
        "flagged": flagged,
        "list_downloaded_at": cache_data.get("downloaded_at"),
    }


def summary(payload: dict[str, Any]) -> str:
    if not payload.get("checked", False):
        return f"scam_list error={payload.get('error', 'unavailable')}"
    return "scam_list FLAGGED" if payload["flagged"] else "scam_list no match"

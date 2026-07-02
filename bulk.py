"""bulk.py — CSV of addresses in, triage columns out.

Reuses run_all_staged() per address for balance/first-last-seen/
dormancy/sanctions, and cluster_by_common_input() across the whole
batch's collected txs so addresses that share a transaction anywhere in
the batch (not just directly against each other) surface a common
cluster_id — the kind of hidden connection bulk triage exists to reveal.

Not parallelized across addresses (each address's own 4 providers already
run in parallel via run_all_staged) — sequential batches are simpler and
correct; worth revisiting if triage of large batches proves too slow.
"""

from __future__ import annotations

import csv
from typing import Any

from clustering import cluster_by_common_input
from core_ops import run_all_staged
from enrichment.providers import blockstream

DORMANCY_FLAG_DAYS = 365
HIGH_BALANCE_FLAG_BTC = 1.0

TRIAGE_FIELDNAMES = [
    "address",
    "valid",
    "error",
    "balance_btc",
    "balance_sats",
    "tx_count",
    "first_seen",
    "last_seen",
    "dormancy_days",
    "cluster_id",
    "sanctions_hit",
    "wallet_id",
    "risk_flags",
]


def _risk_flags(staged: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    ofac = staged.get("ofac_sdn", {})
    if ofac.get("sanctioned"):
        flags.append("sanctioned")
    if not ofac.get("checked", False):
        flags.append("sanctions_unavailable")

    dormancy = staged.get("dormancy_days")
    if dormancy is not None and dormancy >= DORMANCY_FLAG_DAYS:
        flags.append("dormant")

    blockstream_data = staged.get("blockstream", {})
    if "error" in blockstream_data:
        flags.append("balance_fetch_error")
    elif blockstream_data.get("balance_btc", 0) >= HIGH_BALANCE_FLAG_BTC:
        flags.append("high_balance")

    return flags


def triage_addresses(addresses: list[str]) -> list[dict[str, Any]]:
    """Run the full Phase 1 staged query per address, plus common-input
    clustering across the whole batch's fetched txs. Returns one row
    dict (TRIAGE_FIELDNAMES shape) per input address, in input order.
    """
    staged_by_address: dict[str, dict[str, Any]] = {}
    all_txs: list[dict[str, Any]] = []

    for address in addresses:
        staged = run_all_staged(address)
        staged_by_address[address] = staged
        if staged.get("valid") and "error" not in staged:
            try:
                all_txs.extend(blockstream.fetch_recent_txs(staged["target"]))
            except Exception:
                pass

    clusters = cluster_by_common_input(all_txs)

    rows: list[dict[str, Any]] = []
    for address in addresses:
        staged = staged_by_address[address]
        row = dict.fromkeys(TRIAGE_FIELDNAMES, "")
        row["address"] = address
        row["valid"] = staged.get("valid", False)

        if not staged.get("valid") or "error" in staged:
            row["error"] = staged.get("error", "")
            rows.append(row)
            continue

        target = staged["target"]
        blockstream_data = staged.get("blockstream", {})
        row["balance_btc"] = blockstream_data.get("balance_btc", "")
        row["balance_sats"] = blockstream_data.get("balance_sats", "")
        row["tx_count"] = blockstream_data.get("tx_count", "")
        row["first_seen"] = staged.get("first_seen", "")
        row["last_seen"] = staged.get("last_seen", "")
        row["dormancy_days"] = staged.get("dormancy_days", "")
        row["cluster_id"] = clusters.get(target, "")
        row["sanctions_hit"] = staged.get("ofac_sdn", {}).get("sanctioned", "")
        row["wallet_id"] = staged.get("walletexplorer", {}).get("wallet_id", "")
        row["risk_flags"] = ";".join(_risk_flags(staged))
        rows.append(row)

    return rows


def read_addresses_csv(path: str) -> list[str]:
    """Read a CSV of addresses. Accepts either a bare single-column list
    or a header row containing an "address" column (any other columns
    are ignored)."""
    with open(path, newline="") as f:
        rows = [row for row in csv.reader(f) if row and row[0].strip()]
    if not rows:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    if "address" in header:
        idx = header.index("address")
        return [row[idx].strip() for row in rows[1:] if len(row) > idx and row[idx].strip()]
    return [row[0].strip() for row in rows]


def write_triage_csv(rows: list[dict[str, Any]], out_path: str) -> str:
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRIAGE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def run_bulk_triage(in_path: str, out_path: str) -> str:
    addresses = read_addresses_csv(in_path)
    rows = triage_addresses(addresses)
    return write_triage_csv(rows, out_path)

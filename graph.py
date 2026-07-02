"""Graph-walk engine — N-hop neighbor expansion from a seed BTC address.

The core Phase 2 differentiator: for every tx touching an address, pull
the *other* parties in that tx (all other input and output addresses) as
neighbors, and recurse to depth N. No StealthOps analog.

Edges are the naive fully-connected input-address -> output-address pairs
observed per tx (excluding self-loops) — this deliberately over-connects
(a tx with 3 inputs and 2 outputs isn't really "every input paid every
output"). Clustering heuristics (common-input-ownership, change-address
detection) refine this raw graph in a later Phase 2 chunk; this module
just captures what's actually on-chain.

Bounded by design: each frontier address is expanded using only its most
recent page of txs (blockstream.fetch_recent_txs, not the fully paginated
fetch_tx_history), and neighbor count per hop is capped, since a walk can
fan out to many addresses and a high-degree hub (exchange, mixer) could
otherwise multiply request counts unboundedly.
"""

from __future__ import annotations

from typing import Any

from core_ops import BTC_ADDRESS_TYPES, Chain, classify_target
from enrichment.providers import blockstream

DEFAULT_MAX_NEIGHBORS_PER_HOP = 25


def _tx_edges(tx: dict[str, Any]) -> tuple[set[str], list[tuple[str, str, int]]]:
    """Return (all_addresses_in_tx, [(from_address, to_address, value_sats), ...])."""
    vin_addrs = {
        v["prevout"]["scriptpubkey_address"]
        for v in tx.get("vin", [])
        if v.get("prevout", {}).get("scriptpubkey_address")
    }
    vout_entries = [
        (o["scriptpubkey_address"], o.get("value", 0)) for o in tx.get("vout", []) if o.get("scriptpubkey_address")
    ]
    all_addrs = vin_addrs | {addr for addr, _ in vout_entries}

    edges = [
        (in_addr, out_addr, value)
        for in_addr in vin_addrs
        for out_addr, value in vout_entries
        if in_addr != out_addr
    ]
    return all_addrs, edges


def expand_neighbors(
    address: str, depth: int = 1, max_neighbors_per_hop: int = DEFAULT_MAX_NEIGHBORS_PER_HOP
) -> dict[str, Any]:
    """BFS neighbor expansion from `address` out to `depth` hops.

    Returns a dict with:
      seed, requested_depth, valid, error (if invalid/unsupported target)
      nodes: {address: {"depth": int}}
      edges: [{"txid", "from", "to", "value_sats", "block_time"}]
      truncated: True if any hop's neighbor set was capped
      fetch_errors: {address: "error message"} for addresses whose tx fetch failed
    """
    classified = classify_target(address)
    out: dict[str, Any] = {"seed": classified.target, "requested_depth": depth, "valid": classified.valid}
    if not classified.valid:
        out["error"] = classified.detail
        return out
    if classified.chain != Chain.BITCOIN or classified.target_type not in BTC_ADDRESS_TYPES:
        out["error"] = (
            "expand_neighbors currently only supports BTC address targets; "
            f"got chain={classified.chain} target_type={classified.target_type}"
        )
        return out
    if depth < 1:
        out["error"] = f"depth must be >= 1, got {depth}"
        return out

    seed = classified.target
    nodes: dict[str, dict[str, int]] = {seed: {"depth": 0}}
    edges: list[dict[str, Any]] = []
    fetch_errors: dict[str, str] = {}
    truncated = False

    frontier = {seed}
    for current_depth in range(1, depth + 1):
        next_frontier: set[str] = set()
        for addr in frontier:
            try:
                txs = blockstream.fetch_recent_txs(addr)
            except Exception as exc:
                fetch_errors[addr] = str(exc)
                continue

            for tx in txs:
                txid = tx.get("txid")
                block_time = tx.get("status", {}).get("block_time")
                all_addrs, tx_edges = _tx_edges(tx)
                if len(all_addrs) < 2:
                    continue

                for from_addr, to_addr, value_sats in tx_edges:
                    edges.append(
                        {
                            "txid": txid,
                            "from": from_addr,
                            "to": to_addr,
                            "value_sats": value_sats,
                            "block_time": block_time,
                        }
                    )

                for neighbor in all_addrs - {addr}:
                    if neighbor not in nodes:
                        next_frontier.add(neighbor)

        if len(next_frontier) > max_neighbors_per_hop:
            next_frontier = set(sorted(next_frontier)[:max_neighbors_per_hop])
            truncated = True

        for neighbor in next_frontier:
            nodes[neighbor] = {"depth": current_depth}

        frontier = next_frontier
        if not frontier:
            break

    out["nodes"] = nodes
    out["edges"] = edges
    out["truncated"] = truncated
    out["fetch_errors"] = fetch_errors
    return out

"""Graph-walk engine — N-hop neighbor expansion from a seed address, across
BTC, Tron, and ETH.

The core Phase 2 differentiator: for every tx/transfer touching an
address, pull the *other* parties as neighbors, and recurse to depth N.
No StealthOps analog.

BTC edges are the naive fully-connected input-address -> output-address
pairs observed per tx (excluding self-loops) — this deliberately
over-connects (a tx with 3 inputs and 2 outputs isn't really "every input
paid every output"). Clustering heuristics (common-input-ownership,
change-address detection) refine this raw graph in a later Phase 2 chunk;
this module just captures what's actually on-chain.

Tron/EVM edges are simpler: a token transfer is already a single
from -> to pair (account model, no multi-input/output ambiguity), built
from tron.fetch_recent_usdt_transfers()/evm.fetch_recent_token_transfers().
Their `amount`/`symbol`/timestamp fields differ in shape from BTC's raw
vin/vout (and from each other — Tron's block_timestamp is milliseconds,
Etherscan's timestamp is seconds), so edges carry `value`+`symbol` instead
of BTC's `value_sats`; draw.py/formatter.py branch on which is present.

Bounded by design: each frontier address is expanded using only its most
recent page of activity (blockstream.fetch_recent_txs /
tron.fetch_recent_usdt_transfers / evm.fetch_recent_token_transfers — not
the fully paginated history functions), and neighbor count per hop is
capped, since a walk can fan out to many addresses and a high-degree hub
(exchange, mixer) could otherwise multiply request counts unboundedly.

ENS names are not supported as a seed/neighbor here (matching evm.run()'s
own contract) — resolve to an address first via core_ops.run_all_staged().
"""

from __future__ import annotations

from typing import Any

from core_ops import BTC_ADDRESS_TYPES, Chain, TargetType, classify_target
from enrichment.providers import blockstream, evm, tron

DEFAULT_MAX_NEIGHBORS_PER_HOP = 25

_SUPPORTED_TARGET_TYPES = {
    Chain.BITCOIN: BTC_ADDRESS_TYPES,
    Chain.TRON: {TargetType.TRON_ADDRESS},
    Chain.ETHEREUM: {TargetType.ETH_ADDRESS},
}


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


def _fetch_frontier_edges(chain: str, addr: str, key: str) -> tuple[set[str], list[dict[str, Any]]]:
    """Fetch one address' recent activity and return (all_addresses_touched, edges).

    Raises on fetch failure (HTTP error, rate limit, missing key) --
    callers catch per-address and degrade gracefully, same contract as
    the underlying fetch_recent_* functions.
    """
    if chain == Chain.BITCOIN:
        all_addrs: set[str] = set()
        edges: list[dict[str, Any]] = []
        for tx in blockstream.fetch_recent_txs(addr):
            txid = tx.get("txid")
            block_time = tx.get("status", {}).get("block_time")
            tx_addrs, tx_edges = _tx_edges(tx)
            if len(tx_addrs) < 2:
                continue
            all_addrs |= tx_addrs
            edges.extend(
                {"txid": txid, "from": f, "to": t, "value_sats": v, "block_time": block_time}
                for f, t, v in tx_edges
            )
        return all_addrs, edges

    if chain == Chain.TRON:
        transfers = tron.fetch_recent_usdt_transfers(addr, key)
        return _token_transfer_edges(transfers, timestamp_field="block_timestamp", timestamp_divisor=1000)

    if chain == Chain.ETHEREUM:
        transfers = evm.fetch_recent_token_transfers(addr, key)
        return _token_transfer_edges(transfers, timestamp_field="timestamp", timestamp_divisor=1)

    raise ValueError(f"unsupported chain: {chain}")


def _token_transfer_edges(
    transfers: list[dict[str, Any]], timestamp_field: str, timestamp_divisor: int
) -> tuple[set[str], list[dict[str, Any]]]:
    """Build (all_addresses, edges) from tron/evm's already-formatted
    from/to/amount/symbol transfer dicts (account-model: each transfer IS
    a single edge, unlike BTC's multi-input/output tx)."""
    all_addrs: set[str] = set()
    edges: list[dict[str, Any]] = []
    for transfer in transfers:
        from_addr, to_addr = transfer.get("from"), transfer.get("to")
        if not from_addr or not to_addr or from_addr == to_addr:
            continue
        all_addrs.add(from_addr)
        all_addrs.add(to_addr)
        raw_ts = transfer.get(timestamp_field)
        edges.append(
            {
                "txid": transfer.get("txid"),
                "from": from_addr,
                "to": to_addr,
                "value": transfer.get("amount"),
                "symbol": transfer.get("symbol"),
                "block_time": raw_ts // timestamp_divisor if raw_ts is not None else None,
            }
        )
    return all_addrs, edges


def _key_for_chain(chain: str) -> str:
    if chain == Chain.TRON:
        import keystore

        return keystore.get_key("TRONGRID_API_KEY")
    if chain == Chain.ETHEREUM:
        import keystore

        return keystore.get_key("ETHERSCAN_API_KEY")
    return ""


def expand_neighbors(
    address: str, depth: int = 1, max_neighbors_per_hop: int = DEFAULT_MAX_NEIGHBORS_PER_HOP
) -> dict[str, Any]:
    """BFS neighbor expansion from `address` out to `depth` hops, across
    BTC, Tron, and ETH.

    Returns a dict with:
      seed, requested_depth, valid, error (if invalid/unsupported target)
      nodes: {address: {"depth": int}}
      edges: BTC: [{"txid", "from", "to", "value_sats", "block_time"}]
             Tron/EVM: [{"txid", "from", "to", "value", "symbol", "block_time"}]
      truncated: True if any hop's neighbor set was capped
      fetch_errors: {address: "error message"} for addresses whose fetch failed
    """
    classified = classify_target(address)
    out: dict[str, Any] = {"seed": classified.target, "requested_depth": depth, "valid": classified.valid}
    if not classified.valid:
        out["error"] = classified.detail
        return out
    if classified.target_type not in _SUPPORTED_TARGET_TYPES.get(classified.chain, set()):
        out["error"] = (
            "expand_neighbors currently only supports BTC, Tron, and ETH address targets; "
            f"got chain={classified.chain} target_type={classified.target_type}"
        )
        return out
    if depth < 1:
        out["error"] = f"depth must be >= 1, got {depth}"
        return out

    chain = classified.chain
    key = _key_for_chain(chain)
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
                all_addrs, addr_edges = _fetch_frontier_edges(chain, addr, key)
            except Exception as exc:
                fetch_errors[addr] = str(exc)
                continue

            edges.extend(addr_edges)
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

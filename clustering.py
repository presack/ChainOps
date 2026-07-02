"""Clustering heuristics — common-input-ownership, change-address
detection, and peel-chain detection.

cluster_by_common_input() and detect_change_output() operate on raw
Blockstream tx objects (same shape as blockstream.fetch_recent_txs /
fetch_tx_history) rather than graph.py's edge list, since correct
common-input clustering needs the *full* set of inputs per tx — a graph
edge is just one input/output pair.

detect_peel_chain() does its own linear forward walk (distinct from
graph.py's breadth-first expand_neighbors) since a peel chain is
inherently a single sequential path, not a fan-out.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from core_ops import BTC_ADDRESS_TYPES, Chain, classify_target
from enrichment.providers import blockstream

# An output value is treated as "round" (human-chosen payment amount,
# not leftover change) if it's a multiple of this many sats (0.0001 BTC).
ROUND_AMOUNT_SATS_DIVISOR = 10000

DEFAULT_PEEL_CHAIN_MAX_HOPS = 20
DEFAULT_CARRY_FORWARD_RATIO = 0.8


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._parent[rx] = ry

    def members(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for addr in self._parent:
            groups.setdefault(self.find(addr), []).append(addr)
        return groups


def _tx_input_addresses(tx: dict[str, Any]) -> list[str]:
    return [
        v["prevout"]["scriptpubkey_address"]
        for v in tx.get("vin", [])
        if v.get("prevout", {}).get("scriptpubkey_address")
    ]


def cluster_by_common_input(txs: list[dict[str, Any]]) -> dict[str, str]:
    """Union addresses that co-occur as inputs in the same tx — you need
    every input's private key to sign a tx, so multiple inputs implies
    one owner. Returns {address: cluster_id}, where cluster_id is the
    lexicographically smallest address in that cluster (deterministic,
    no external ID allocator needed).
    """
    uf = _UnionFind()
    for tx in txs:
        vin_addrs = _tx_input_addresses(tx)
        for addr in vin_addrs:
            uf.find(addr)
        for a, b in zip(vin_addrs, vin_addrs[1:]):
            uf.union(a, b)

    return {addr: min(members) for members in uf.members().values() for addr in members}


def _is_round_amount(value_sats: int) -> bool:
    return value_sats % ROUND_AMOUNT_SATS_DIVISOR == 0


def detect_change_output(tx: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort guess at which output (if any) is change returning to
    the sender, vs. a genuine payment to a third party. Heuristics, in
    order of precedence:

      1. address-type match: wallets typically produce change in their
         own address format, so an output type matching the majority
         input type (when not all outputs match) is the stronger signal.
      2. round-number: among remaining candidates, a human-chosen payment
         amount tends to be round; leftover change is arbitrary satoshis.

    Returns the matched vout dict plus a "change_reason" field, or None
    if there's no clear signal (single output, or heuristics don't
    narrow to exactly one candidate).
    """
    vout = [o for o in tx.get("vout", []) if o.get("scriptpubkey_address")]
    if len(vout) < 2:
        return None

    input_types = [
        v["prevout"]["scriptpubkey_type"] for v in tx.get("vin", []) if v.get("prevout", {}).get("scriptpubkey_type")
    ]
    if not input_types:
        return None
    majority_type = Counter(input_types).most_common(1)[0][0]

    type_matches = [o for o in vout if o.get("scriptpubkey_type") == majority_type]
    type_mismatches = [o for o in vout if o.get("scriptpubkey_type") != majority_type]

    candidates = vout
    reason = None
    if type_matches and type_mismatches:
        candidates = type_matches
        reason = "address_type_match"

    if len(candidates) == 1:
        result = dict(candidates[0])
        result["change_reason"] = reason or "only_candidate"
        return result

    non_round = [o for o in candidates if not _is_round_amount(o.get("value", 0))]
    if len(non_round) == 1:
        result = dict(non_round[0])
        result["change_reason"] = f"{reason}+non_round_amount" if reason else "non_round_amount"
        return result

    return None


def detect_peel_chain(
    seed: str,
    max_hops: int = DEFAULT_PEEL_CHAIN_MAX_HOPS,
    carry_forward_ratio: float = DEFAULT_CARRY_FORWARD_RATIO,
) -> dict[str, Any]:
    """Walk forward from `seed` looking for the peel-chain pattern: each
    hop's spending tx has one dominant "carry forward" output (>=
    carry_forward_ratio of total output value) plus one or more small
    "leaf" outputs, with the carry-forward continuing to a new address
    each time — "one large carry forward output + many small leaf
    outputs, repeating" per the first session's manual trace.
    """
    classified = classify_target(seed)
    out: dict[str, Any] = {"seed": classified.target, "valid": classified.valid}
    if not classified.valid:
        out["error"] = classified.detail
        return out
    if classified.chain != Chain.BITCOIN or classified.target_type not in BTC_ADDRESS_TYPES:
        out["error"] = (
            "detect_peel_chain currently only supports BTC address targets; "
            f"got chain={classified.chain} target_type={classified.target_type}"
        )
        return out

    hops: list[dict[str, Any]] = []
    leaf_addresses: list[str] = []
    current = classified.target
    visited = {current}
    broke_because = "max_hops_reached"

    for _ in range(max_hops):
        try:
            txs = blockstream.fetch_recent_txs(current)
        except Exception as exc:
            broke_because = f"fetch error: {exc}"
            break

        spend_tx = next((tx for tx in txs if current in _tx_input_addresses(tx)), None)
        if spend_tx is None:
            broke_because = "no outgoing spend found"
            break

        vout = [o for o in spend_tx.get("vout", []) if o.get("scriptpubkey_address")]
        if len(vout) < 2:
            broke_because = "spend tx has fewer than 2 outputs (not a peel pattern)"
            break

        total_out = sum(o.get("value", 0) for o in vout)
        if total_out == 0:
            broke_because = "zero-value outputs"
            break

        vout_sorted = sorted(vout, key=lambda o: o.get("value", 0), reverse=True)
        carry, leaves = vout_sorted[0], vout_sorted[1:]

        if carry.get("value", 0) / total_out < carry_forward_ratio:
            broke_because = "no dominant carry-forward output"
            break

        next_addr = carry["scriptpubkey_address"]
        if next_addr in visited:
            broke_because = "carry-forward address already visited (cycle)"
            break

        hops.append(
            {
                "txid": spend_tx.get("txid"),
                "from": current,
                "carry_forward": {"address": next_addr, "value_sats": carry.get("value", 0)},
                "leaves": [{"address": o["scriptpubkey_address"], "value_sats": o.get("value", 0)} for o in leaves],
            }
        )
        leaf_addresses.extend(o["scriptpubkey_address"] for o in leaves)
        visited.add(next_addr)
        current = next_addr
    else:
        broke_because = "max_hops_reached"

    out["hops"] = hops
    out["chain_length"] = len(hops)
    out["leaf_addresses"] = leaf_addresses
    out["broke_because"] = broke_because
    return out

from unittest.mock import patch

from graph import expand_neighbors

SEED = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"


def _tx(txid, block_time, vin_addrs, vout_pairs):
    return {
        "txid": txid,
        "status": {"confirmed": True, "block_time": block_time},
        "vin": [{"prevout": {"scriptpubkey_address": a}} for a in vin_addrs],
        "vout": [{"scriptpubkey_address": addr, "value": value} for addr, value in vout_pairs],
    }


TX1 = _tx("tx1", 1000, [SEED], [("addrB", 100), ("addrC", 200)])
TX2 = _tx("tx2", 2000, ["addrB"], [("addrD", 50)])

_TXS_BY_ADDRESS = {SEED: [TX1], "addrB": [TX2], "addrC": []}


def _fetch_side_effect(addr):
    return _TXS_BY_ADDRESS.get(addr, [])


@patch("graph.blockstream.fetch_recent_txs", side_effect=_fetch_side_effect)
def test_depth_one_finds_direct_neighbors(fetch):
    result = expand_neighbors(SEED, depth=1)

    assert result["valid"] is True
    assert set(result["nodes"]) == {SEED, "addrB", "addrC"}
    assert result["nodes"][SEED]["depth"] == 0
    assert result["nodes"]["addrB"]["depth"] == 1
    assert result["nodes"]["addrC"]["depth"] == 1
    assert {"txid": "tx1", "from": SEED, "to": "addrB", "value_sats": 100, "block_time": 1000} in result["edges"]
    assert {"txid": "tx1", "from": SEED, "to": "addrC", "value_sats": 200, "block_time": 1000} in result["edges"]
    fetch.assert_called_once_with(SEED)


@patch("graph.blockstream.fetch_recent_txs", side_effect=_fetch_side_effect)
def test_depth_two_recurses_into_hop_one_neighbors(fetch):
    result = expand_neighbors(SEED, depth=2)

    assert set(result["nodes"]) == {SEED, "addrB", "addrC", "addrD"}
    assert result["nodes"]["addrD"]["depth"] == 2
    assert {"txid": "tx2", "from": "addrB", "to": "addrD", "value_sats": 50, "block_time": 2000} in result["edges"]
    assert fetch.call_count == 3  # seed, addrB, addrC


@patch("graph.blockstream.fetch_recent_txs", side_effect=_fetch_side_effect)
def test_truncates_when_neighbor_count_exceeds_cap(fetch):
    result = expand_neighbors(SEED, depth=1, max_neighbors_per_hop=1)

    assert result["truncated"] is True
    assert len(result["nodes"]) == 2  # seed + exactly one neighbor kept


@patch("graph.blockstream.fetch_recent_txs")
def test_excludes_self_loop_edges(fetch):
    change_tx = _tx("tx3", 3000, [SEED], [(SEED, 900), ("addrB", 100)])
    fetch.return_value = [change_tx]

    result = expand_neighbors(SEED, depth=1)

    assert all(e["from"] != e["to"] for e in result["edges"])
    assert any(e["to"] == "addrB" for e in result["edges"])


@patch("graph.blockstream.fetch_recent_txs")
def test_fetch_failure_is_recorded_not_fatal(fetch):
    def side_effect(addr):
        if addr == SEED:
            return [TX1]
        raise ConnectionError("timeout")

    fetch.side_effect = side_effect

    result = expand_neighbors(SEED, depth=2)

    assert "addrB" in result["fetch_errors"] or "addrC" in result["fetch_errors"]
    assert SEED in result["nodes"]


def test_rejects_invalid_target():
    result = expand_neighbors("not-a-real-target!!")
    assert result["valid"] is False
    assert "error" in result
    assert "nodes" not in result


def test_rejects_non_btc_chain():
    result = expand_neighbors("vitalik.eth")
    assert result["valid"] is True
    assert "error" in result
    assert "nodes" not in result


def test_rejects_non_address_btc_target():
    txid = "a" * 64
    result = expand_neighbors(txid)
    assert "error" in result
    assert "nodes" not in result


def test_rejects_depth_below_one():
    result = expand_neighbors(SEED, depth=0)
    assert "error" in result
    assert "depth must be" in result["error"]


@patch("graph.blockstream.fetch_recent_txs", return_value=[])
def test_stops_early_when_frontier_empties(fetch):
    result = expand_neighbors(SEED, depth=5)
    assert result["nodes"] == {SEED: {"depth": 0}}
    fetch.assert_called_once_with(SEED)

from unittest.mock import patch

import pytest

from graph import expand_neighbors

SEED = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"


@pytest.fixture(autouse=True)
def _mock_node_tagging(monkeypatch):
    # graph._tag_nodes() calls ofac_sdn.check_addresses and
    # scam_list.check_addresses for every walk (all chains) and
    # contract_info.classify_address for EVM walks -- default all to
    # "nothing flagged" so existing tests don't need to know about
    # tagging; tests that specifically exercise tagging override these
    # individually.
    monkeypatch.setattr(
        "enrichment.providers.ofac_sdn.check_addresses", lambda addrs, chain: {a: False for a in addrs}
    )
    monkeypatch.setattr(
        "enrichment.providers.scam_list.check_addresses", lambda addrs, chain: {a: False for a in addrs}
    )
    monkeypatch.setattr(
        "enrichment.providers.contract_info.classify_address",
        lambda addr: {"kind": "eoa", "delegate_address": None, "error": None},
    )


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


def test_rejects_ens_name():
    # ENS names aren't resolved here, matching evm.run()'s contract --
    # resolve to an address first via core_ops.run_all_staged().
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
    assert set(result["nodes"]) == {SEED}
    assert result["nodes"][SEED]["depth"] == 0
    fetch.assert_called_once_with(SEED)


# --- Tron ---

TRON_SEED = "TXFBqBbqJommqZf7BV8NNYzePh97UmJodJ"
TRON_NEIGHBOR = "TQ1acB6EzwLVWsmE7fn4g8mq3kjGzxbEeN"


def _tron_transfer(txid, from_addr, to_addr, timestamp_ms=1_700_000_000_000, amount=10.0):
    return {"txid": txid, "from": from_addr, "to": to_addr, "amount": amount, "symbol": "USDT", "block_timestamp": timestamp_ms}


@patch("graph._key_for_chain", return_value="")
@patch("graph.tron.fetch_recent_usdt_transfers")
def test_tron_depth_one_finds_direct_neighbors(fetch, _key):
    fetch.return_value = [_tron_transfer("t1", TRON_SEED, TRON_NEIGHBOR)]

    result = expand_neighbors(TRON_SEED, depth=1)

    assert result["valid"] is True
    assert set(result["nodes"]) == {TRON_SEED, TRON_NEIGHBOR}
    assert result["nodes"][TRON_NEIGHBOR]["depth"] == 1
    edge = result["edges"][0]
    assert edge == {
        "txid": "t1",
        "from": TRON_SEED,
        "to": TRON_NEIGHBOR,
        "value": 10.0,
        "symbol": "USDT",
        "block_time": 1_700_000_000,
    }
    fetch.assert_called_once_with(TRON_SEED, "")


@patch("graph._key_for_chain", return_value="")
@patch("graph.tron.fetch_recent_usdt_transfers")
def test_tron_excludes_self_transfer_edges(fetch, _key):
    fetch.return_value = [_tron_transfer("t1", TRON_SEED, TRON_SEED)]

    result = expand_neighbors(TRON_SEED, depth=1)

    assert result["edges"] == []
    assert set(result["nodes"]) == {TRON_SEED}


@patch("graph._key_for_chain", return_value="")
@patch("graph.tron.fetch_recent_usdt_transfers", side_effect=ConnectionError("timeout"))
def test_tron_fetch_failure_is_recorded_not_fatal(fetch, _key):
    result = expand_neighbors(TRON_SEED, depth=1)

    assert TRON_SEED in result["fetch_errors"]
    assert set(result["nodes"]) == {TRON_SEED}
    assert result["nodes"][TRON_SEED]["depth"] == 0


# --- EVM ---

EVM_SEED = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
EVM_NEIGHBOR = "0x" + "1" * 40


def _evm_transfer(txid, from_addr, to_addr, timestamp_s=1_700_000_000, amount=5.0):
    return {"txid": txid, "from": from_addr, "to": to_addr, "amount": amount, "symbol": "USDC", "timestamp": timestamp_s}


@patch("graph._key_for_chain", return_value="my-etherscan-key")
@patch("graph.evm.fetch_recent_token_transfers")
def test_evm_depth_one_finds_direct_neighbors(fetch, _key):
    fetch.return_value = [_evm_transfer("0xa", EVM_SEED, EVM_NEIGHBOR)]

    result = expand_neighbors(EVM_SEED, depth=1)

    assert result["valid"] is True
    assert set(result["nodes"]) == {EVM_SEED, EVM_NEIGHBOR}
    edge = result["edges"][0]
    assert edge == {
        "txid": "0xa",
        "from": EVM_SEED,
        "to": EVM_NEIGHBOR,
        "value": 5.0,
        "symbol": "USDC",
        "block_time": 1_700_000_000,
    }
    fetch.assert_called_once_with(EVM_SEED, "my-etherscan-key")


@patch("graph._key_for_chain", return_value="my-etherscan-key")
@patch("graph.evm.fetch_recent_token_transfers", side_effect=RuntimeError("token transfer lookup failed: NOTOK"))
def test_evm_fetch_failure_is_recorded_not_fatal(fetch, _key):
    result = expand_neighbors(EVM_SEED, depth=1)

    assert EVM_SEED in result["fetch_errors"]
    assert "NOTOK" in result["fetch_errors"][EVM_SEED]


# --- node tagging: sanctions (all chains) + contract detection (EVM only) ---


@patch("graph.blockstream.fetch_recent_txs", side_effect=_fetch_side_effect)
def test_btc_nodes_flagged_sanctioned_from_ofac_check(fetch, monkeypatch):
    monkeypatch.setattr(
        "enrichment.providers.ofac_sdn.check_addresses",
        lambda addrs, chain: {a: (a == "addrB") for a in addrs},
    )

    result = expand_neighbors(SEED, depth=1)

    assert result["nodes"][SEED]["sanctioned"] is False
    assert result["nodes"]["addrB"]["sanctioned"] is True
    assert result["nodes"]["addrC"]["sanctioned"] is False
    assert "is_contract" not in result["nodes"][SEED]  # BTC has no contract concept


@patch("graph._key_for_chain", return_value="my-etherscan-key")
@patch("graph.evm.fetch_recent_token_transfers")
def test_evm_nodes_flagged_contract_and_sanctioned(fetch, _key, monkeypatch):
    fetch.return_value = [_evm_transfer("0xa", EVM_SEED, EVM_NEIGHBOR)]
    monkeypatch.setattr(
        "enrichment.providers.ofac_sdn.check_addresses",
        lambda addrs, chain: {a: (a == EVM_NEIGHBOR) for a in addrs},
    )
    monkeypatch.setattr(
        "enrichment.providers.contract_info.classify_address",
        lambda addr: {"kind": "contract", "delegate_address": None, "error": None}
        if addr == EVM_NEIGHBOR
        else {"kind": "eoa", "delegate_address": None, "error": None},
    )

    result = expand_neighbors(EVM_SEED, depth=1)

    assert result["nodes"][EVM_SEED]["is_contract"] is False
    assert result["nodes"][EVM_SEED]["sanctioned"] is False
    assert result["nodes"][EVM_NEIGHBOR]["is_contract"] is True
    assert result["nodes"][EVM_NEIGHBOR]["sanctioned"] is True


@patch("graph._key_for_chain", return_value="my-etherscan-key")
@patch("graph.evm.fetch_recent_token_transfers")
def test_evm_nodes_flagged_scam_listed(fetch, _key, monkeypatch):
    fetch.return_value = [_evm_transfer("0xa", EVM_SEED, EVM_NEIGHBOR)]
    monkeypatch.setattr(
        "enrichment.providers.scam_list.check_addresses",
        lambda addrs, chain: {a: (a == EVM_NEIGHBOR) for a in addrs},
    )

    result = expand_neighbors(EVM_SEED, depth=1)

    assert result["nodes"][EVM_SEED]["scam_flagged"] is False
    assert result["nodes"][EVM_NEIGHBOR]["scam_flagged"] is True


@patch("graph.blockstream.fetch_recent_txs", side_effect=_fetch_side_effect)
def test_btc_nodes_have_no_scam_flag_since_source_is_evm_only(fetch):
    result = expand_neighbors(SEED, depth=1)

    assert result["nodes"][SEED]["scam_flagged"] is False  # present, always False for non-EVM chains


@patch("graph._key_for_chain", return_value="")
@patch("graph.tron.fetch_recent_usdt_transfers")
def test_tron_nodes_have_no_contract_flag(fetch, _key):
    fetch.return_value = [_tron_transfer("t1", TRON_SEED, TRON_NEIGHBOR)]

    result = expand_neighbors(TRON_SEED, depth=1)

    assert "is_contract" not in result["nodes"][TRON_SEED]  # Tron contract detection is out of scope for now
    assert result["nodes"][TRON_SEED]["sanctioned"] is False


@patch("graph._key_for_chain", return_value="my-etherscan-key")
@patch("graph.evm.fetch_recent_token_transfers")
def test_evm_node_tagging_failure_degrades_gracefully(fetch, _key, monkeypatch):
    fetch.return_value = []
    monkeypatch.setattr(
        "enrichment.providers.contract_info.classify_address", lambda addr: (_ for _ in ()).throw(RuntimeError("rpc down"))
    )

    result = expand_neighbors(EVM_SEED, depth=1)

    assert result["nodes"][EVM_SEED]["is_contract"] is False  # unclassifiable defaults to not-a-contract, not a crash

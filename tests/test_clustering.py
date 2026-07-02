from unittest.mock import patch

from clustering import cluster_by_common_input, detect_change_output, detect_peel_chain

SEED = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"


def _tx(txid, vin_addrs, vout, vin_type="p2pkh"):
    return {
        "txid": txid,
        "status": {"confirmed": True, "block_time": 1000},
        "vin": [{"prevout": {"scriptpubkey_address": a, "scriptpubkey_type": vin_type}} for a in vin_addrs],
        "vout": vout,
    }


def _vout(addr, value, addr_type="p2pkh"):
    return {"scriptpubkey_address": addr, "value": value, "scriptpubkey_type": addr_type}


# --- cluster_by_common_input ---


def test_two_inputs_in_one_tx_are_clustered():
    txs = [_tx("t1", ["A", "B"], [_vout("X", 100)])]
    result = cluster_by_common_input(txs)
    assert result["A"] == result["B"]


def test_three_inputs_all_cluster_together():
    txs = [_tx("t1", ["A", "B", "C"], [_vout("X", 100)])]
    result = cluster_by_common_input(txs)
    assert result["A"] == result["B"] == result["C"]


def test_transitive_clustering_across_multiple_txs():
    txs = [_tx("t1", ["A", "B"], [_vout("X", 100)]), _tx("t2", ["B", "C"], [_vout("Y", 50)])]
    result = cluster_by_common_input(txs)
    assert result["A"] == result["B"] == result["C"]


def test_unrelated_single_input_txs_are_separate_clusters():
    txs = [_tx("t1", ["A"], [_vout("X", 100)]), _tx("t2", ["B"], [_vout("Y", 50)])]
    result = cluster_by_common_input(txs)
    assert result["A"] != result["B"]


def test_cluster_id_is_deterministic_lexicographically_smallest():
    txs = [_tx("t1", ["Zzz", "Aaa"], [_vout("X", 100)])]
    result = cluster_by_common_input(txs)
    assert result["Zzz"] == "Aaa"
    assert result["Aaa"] == "Aaa"


def test_output_only_addresses_are_not_clustered():
    txs = [_tx("t1", ["A"], [_vout("B", 100)])]
    result = cluster_by_common_input(txs)
    assert "B" not in result


# --- detect_change_output ---


def test_single_output_returns_none():
    tx = _tx("t1", ["A"], [_vout("X", 100)])
    assert detect_change_output(tx) is None


def test_address_type_mismatch_identifies_change():
    tx = _tx("t1", ["A"], [_vout("B", 500000, "p2pkh"), _vout("C", 300000, "v0_p2wpkh")], vin_type="p2pkh")
    result = detect_change_output(tx)
    assert result["scriptpubkey_address"] == "B"
    assert result["change_reason"] == "address_type_match"


def test_round_number_identifies_change_when_types_match():
    tx = _tx(
        "t1",
        ["A"],
        [_vout("B", 500000000, "p2pkh"), _vout("C", 297653321, "p2pkh")],
        vin_type="p2pkh",
    )
    result = detect_change_output(tx)
    assert result["scriptpubkey_address"] == "C"
    assert result["change_reason"] == "non_round_amount"


def test_combined_reason_when_both_heuristics_narrow():
    tx = _tx(
        "t1",
        ["A"],
        [
            _vout("B", 500000000, "p2pkh"),  # matches type, round
            _vout("C", 297653321, "p2pkh"),  # matches type, non-round -> change
            _vout("D", 100000, "v0_p2wpkh"),  # wrong type
        ],
        vin_type="p2pkh",
    )
    result = detect_change_output(tx)
    assert result["scriptpubkey_address"] == "C"
    assert result["change_reason"] == "address_type_match+non_round_amount"


def test_ambiguous_case_returns_none():
    tx = _tx("t1", ["A"], [_vout("B", 500000, "p2pkh"), _vout("C", 300000, "p2pkh")], vin_type="p2pkh")
    assert detect_change_output(tx) is None


def test_no_input_type_info_returns_none():
    tx = {"txid": "t1", "vin": [{"prevout": {"scriptpubkey_address": "A"}}], "vout": [_vout("B", 1), _vout("C", 2)]}
    assert detect_change_output(tx) is None


# --- detect_peel_chain ---


@patch("clustering.blockstream.fetch_recent_txs")
def test_peel_chain_follows_dominant_carry_forward(fetch):
    hop1 = _tx("h1", [SEED], [_vout("addrB", 900000), _vout("leaf1", 100000)])
    hop2 = _tx("h2", ["addrB"], [_vout("addrC", 850000), _vout("leaf2", 50000)])
    fetch.side_effect = lambda addr: {SEED: [hop1], "addrB": [hop2], "addrC": []}.get(addr, [])

    result = detect_peel_chain(SEED, max_hops=10)

    assert result["chain_length"] == 2
    assert result["hops"][0]["carry_forward"]["address"] == "addrB"
    assert result["hops"][1]["carry_forward"]["address"] == "addrC"
    assert set(result["leaf_addresses"]) == {"leaf1", "leaf2"}
    assert result["broke_because"] == "no outgoing spend found"


@patch("clustering.blockstream.fetch_recent_txs")
def test_peel_chain_stops_when_no_dominant_output(fetch):
    hop1 = _tx("h1", [SEED], [_vout("addrB", 600000), _vout("addrC", 400000)])
    fetch.side_effect = lambda addr: {SEED: [hop1]}.get(addr, [])

    result = detect_peel_chain(SEED, carry_forward_ratio=0.8)

    assert result["chain_length"] == 0
    assert result["broke_because"] == "no dominant carry-forward output"


@patch("clustering.blockstream.fetch_recent_txs")
def test_peel_chain_stops_on_single_output(fetch):
    hop1 = _tx("h1", [SEED], [_vout("addrB", 900000)])
    fetch.side_effect = lambda addr: {SEED: [hop1]}.get(addr, [])

    result = detect_peel_chain(SEED)
    assert result["chain_length"] == 0
    assert "fewer than 2 outputs" in result["broke_because"]


@patch("clustering.blockstream.fetch_recent_txs")
def test_peel_chain_respects_max_hops(fetch):
    seed_tx = _tx("h0", [SEED], [_vout("addr1", 900000), _vout("leaf0", 100000)])
    tx1 = _tx("h1", ["addr1"], [_vout("addr2", 900000), _vout("leaf1", 100000)])
    tx2 = _tx("h2", ["addr2"], [_vout("addr3", 900000), _vout("leaf2", 100000)])
    fetch.side_effect = lambda addr: {SEED: [seed_tx], "addr1": [tx1], "addr2": [tx2]}.get(addr, [])

    result = detect_peel_chain(SEED, max_hops=3)

    assert result["chain_length"] == 3
    assert result["broke_because"] == "max_hops_reached"


@patch("clustering.blockstream.fetch_recent_txs")
def test_peel_chain_detects_cycle(fetch):
    hop_to_seed = _tx("h1", [SEED], [_vout("addrB", 900000), _vout("leaf1", 100000)])
    hop_back_to_seed = _tx("h2", ["addrB"], [_vout(SEED, 850000), _vout("leaf2", 50000)])
    fetch.side_effect = lambda addr: {SEED: [hop_to_seed], "addrB": [hop_back_to_seed]}.get(addr, [])

    result = detect_peel_chain(SEED, max_hops=10)
    assert result["broke_because"] == "carry-forward address already visited (cycle)"
    assert result["chain_length"] == 1


@patch("clustering.blockstream.fetch_recent_txs")
def test_peel_chain_fetch_error_is_recorded(fetch):
    fetch.side_effect = ConnectionError("timeout")
    result = detect_peel_chain(SEED)
    assert result["chain_length"] == 0
    assert "fetch error" in result["broke_because"]


def test_peel_chain_rejects_invalid_target():
    result = detect_peel_chain("not-a-real-target!!")
    assert result["valid"] is False
    assert "error" in result
    assert "hops" not in result


def test_peel_chain_rejects_non_btc_target():
    result = detect_peel_chain("vitalik.eth")
    assert "error" in result
    assert "hops" not in result

from unittest.mock import Mock, patch

import requests

from enrichment.providers import blockstream

# Publicly reported (Forbes, 2013) as connected to Ross Ulbricht / Dread
# Pirate Roberts during the Silk Road seizure — long public, non-sensitive.
ADDRESS = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"


def _mock_response(json_data, status_code=200):
    resp = Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = ""
    return resp


@patch("enrichment.providers.blockstream.requests.get")
def test_run_computes_balance_and_counts(get: Mock):
    stats = {
        "chain_stats": {"funded_txo_sum": 5000, "spent_txo_sum": 2000, "tx_count": 3},
        "mempool_stats": {"funded_txo_sum": 0, "spent_txo_sum": 0, "tx_count": 0},
    }
    utxos = [{"txid": "a" * 64, "vout": 0, "value": 3000}]
    txs = [{"txid": "b" * 64, "status": {"confirmed": True, "block_time": 1700000000}}]

    get.side_effect = [_mock_response(stats), _mock_response(utxos), _mock_response(txs)]

    result = blockstream.run(ADDRESS, "")

    assert result["source"] == "blockstream"
    assert result["balance_sats"] == 3000
    assert result["balance_btc"] == 3000 / 1e8
    assert result["tx_count"] == 3
    assert result["utxo_count"] == 1
    assert result["last_seen"] == 1700000000
    assert result["recent_txs"] == ["b" * 64]


@patch("enrichment.providers.blockstream.requests.get")
def test_run_marks_unconfirmed_last_seen(get: Mock):
    stats = {
        "chain_stats": {"funded_txo_sum": 0, "spent_txo_sum": 0, "tx_count": 0},
        "mempool_stats": {"funded_txo_sum": 1000, "spent_txo_sum": 0, "tx_count": 1},
    }
    txs = [{"txid": "c" * 64, "status": {"confirmed": False}}]

    get.side_effect = [_mock_response(stats), _mock_response([]), _mock_response(txs)]

    result = blockstream.run(ADDRESS, "")
    assert result["last_seen"] == "unconfirmed"
    assert result["unconfirmed_balance_sats"] == 1000


@patch("enrichment.providers.blockstream.requests.get")
def test_run_rejects_wrong_chain_before_any_http_call(get: Mock):
    result = blockstream.run("vitalik.eth", "")
    assert result["source"] == "blockstream"
    assert "error" in result
    get.assert_not_called()


@patch("enrichment.providers.blockstream.requests.get")
def test_run_rejects_non_address_btc_targets(get: Mock):
    txid = "d" * 64
    result = blockstream.run(txid, "")
    assert result["source"] == "blockstream"
    assert "error" in result
    get.assert_not_called()


@patch("enrichment.providers.blockstream.requests.get")
def test_run_surfaces_http_error(get: Mock):
    get.return_value = _mock_response({}, status_code=503)
    get.return_value.text = "service unavailable"

    result = blockstream.run(ADDRESS, "")
    assert "error" in result
    assert "503" in result["error"]


@patch("enrichment.providers.blockstream.requests.get")
def test_run_degrades_gracefully_with_no_network(get: Mock):
    get.side_effect = requests.exceptions.ConnectionError("no route to host")

    result = blockstream.run(ADDRESS, "")
    assert result["source"] == "blockstream"
    assert "network error" in result["error"]


def test_summary_formats_success():
    payload = {"balance_btc": 0.0003, "tx_count": 2, "utxo_count": 1}
    assert blockstream.summary(payload) == "blockstream balance=0.00030000 BTC tx_count=2 utxos=1"


def test_summary_formats_error():
    payload = {"source": "blockstream", "error": "boom"}
    assert blockstream.summary(payload) == "blockstream error=boom"


def _tx(txid: str) -> dict:
    return {"txid": txid, "status": {"confirmed": True, "block_time": 1600000000}}


@patch("enrichment.providers.blockstream.requests.get")
def test_fetch_tx_history_single_page_stops_pagination(get: Mock):
    first_page = [_tx(f"a{i}") for i in range(10)]
    get.return_value = _mock_response(first_page)

    result = blockstream.fetch_tx_history(ADDRESS)

    assert result == first_page
    get.assert_called_once()


@patch("enrichment.providers.blockstream.requests.get")
def test_fetch_tx_history_paginates_full_pages(get: Mock):
    first_page = [_tx(f"a{i}") for i in range(25)]
    second_page = [_tx(f"b{i}") for i in range(10)]
    get.side_effect = [_mock_response(first_page), _mock_response(second_page)]

    result = blockstream.fetch_tx_history(ADDRESS)

    assert len(result) == 35
    assert get.call_count == 2


@patch("enrichment.providers.blockstream.requests.get")
def test_fetch_tx_history_stops_when_next_page_empty(get: Mock):
    first_page = [_tx(f"a{i}") for i in range(25)]
    get.side_effect = [_mock_response(first_page), _mock_response([])]

    result = blockstream.fetch_tx_history(ADDRESS)

    assert len(result) == 25
    assert get.call_count == 2


@patch("enrichment.providers.blockstream.requests.get")
def test_fetch_tx_history_empty_address_returns_empty_list(get: Mock):
    get.return_value = _mock_response([])

    result = blockstream.fetch_tx_history(ADDRESS)

    assert result == []
    get.assert_called_once()

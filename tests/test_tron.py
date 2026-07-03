from unittest.mock import Mock, patch

import requests

from enrichment.providers import tron

# Tether Treasury on Tron — public, well-known, high USDT transfer volume.
ADDRESS = "TXFBqBbqJommqZf7BV8NNYzePh97UmJodJ"


def _mock_response(json_data, status_code=200):
    resp = Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = ""
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


def _transfer(txid: str, value: str = "1000000") -> dict:
    return {
        "transaction_id": txid,
        "token_info": {"symbol": "USDT", "address": tron.USDT_CONTRACT, "decimals": 6, "name": "Tether USD"},
        "block_timestamp": 1700000000000,
        "from": "TFrom111111111111111111111111111",
        "to": ADDRESS,
        "type": "Transfer",
        "value": value,
    }


@patch("enrichment.providers.tron.requests.get")
def test_run_computes_balance_and_transfers(get: Mock):
    account = {
        "data": [
            {
                "balance": 5_000_000,
                "trc20": [{tron.USDT_CONTRACT: "123000000"}],
            }
        ]
    }
    transfers = {"data": [_transfer("a" * 64)]}

    get.side_effect = [_mock_response(account), _mock_response(transfers)]

    result = tron.run(ADDRESS, "")

    assert result["source"] == "tron"
    assert result["activated"] is True
    assert result["balance_sun"] == 5_000_000
    assert result["balance_trx"] == 5.0
    assert result["trc20_balances"] == {tron.USDT_CONTRACT: "123000000"}
    assert result["usdt_transfer_count"] == 1
    assert result["recent_usdt_transfers"][0]["txid"] == "a" * 64
    assert result["recent_usdt_transfers"][0]["amount"] == 1.0
    assert result["recent_usdt_transfers"][0]["symbol"] == "USDT"


@patch("enrichment.providers.tron.requests.get")
def test_run_handles_unactivated_address(get: Mock):
    get.side_effect = [_mock_response({"data": []}), _mock_response({"data": []})]

    result = tron.run(ADDRESS, "")

    assert result["activated"] is False
    assert result["balance_sun"] == 0
    assert result["balance_trx"] == 0.0
    assert result["trc20_balances"] == {}
    assert result["usdt_transfer_count"] == 0


@patch("enrichment.providers.tron.requests.get")
def test_run_rejects_wrong_chain_before_any_http_call(get: Mock):
    result = tron.run("vitalik.eth", "")
    assert result["source"] == "tron"
    assert "error" in result
    get.assert_not_called()


@patch("enrichment.providers.tron.requests.get")
def test_run_rejects_btc_address(get: Mock):
    result = tron.run("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", "")
    assert result["source"] == "tron"
    assert "error" in result
    get.assert_not_called()


@patch("enrichment.providers.tron.requests.get")
def test_run_surfaces_account_http_error(get: Mock):
    get.return_value = _mock_response({}, status_code=503)
    get.return_value.text = "service unavailable"

    result = tron.run(ADDRESS, "")
    assert "error" in result
    assert "503" in result["error"]
    get.assert_called_once()


@patch("enrichment.providers.tron.requests.get")
def test_run_surfaces_transfers_http_error(get: Mock):
    account = {"data": [{"balance": 0, "trc20": []}]}
    error_resp = _mock_response({}, status_code=500)
    error_resp.text = "internal error"
    get.side_effect = [_mock_response(account), error_resp]

    result = tron.run(ADDRESS, "")
    assert "error" in result
    assert "500" in result["error"]


@patch("enrichment.providers.tron.requests.get")
def test_run_degrades_gracefully_with_no_network(get: Mock):
    get.side_effect = requests.exceptions.ConnectionError("no route to host")

    result = tron.run(ADDRESS, "")
    assert result["source"] == "tron"
    assert "network error" in result["error"]


@patch("enrichment.providers.tron.requests.get")
def test_run_sends_api_key_header(get: Mock):
    get.side_effect = [_mock_response({"data": []}), _mock_response({"data": []})]

    tron.run(ADDRESS, "my-key")

    for call in get.call_args_list:
        assert call.kwargs["headers"] == {"TRON-PRO-API-KEY": "my-key"}


def test_summary_formats_success():
    payload = {"balance_trx": 5.0, "usdt_transfer_count": 3}
    assert tron.summary(payload) == "tron balance=5.000000 TRX usdt_transfers=3"


def test_summary_formats_error():
    payload = {"source": "tron", "error": "boom"}
    assert tron.summary(payload) == "tron error=boom"

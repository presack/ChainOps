from unittest.mock import Mock, patch

import requests

from enrichment.providers import evm

# Vitalik Buterin's public address -- long-public, non-sensitive, high tx volume.
ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"


def _mock_response(json_data, status_code=200):
    resp = Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = ""
    return resp


def _tx(tx_hash: str, timestamp: str = "1700000000") -> dict:
    return {"hash": tx_hash, "timeStamp": timestamp}


def _token_transfer(tx_hash: str, value: str = "1000000000000000000") -> dict:
    return {
        "hash": tx_hash,
        "from": "0x" + "1" * 40,
        "to": ADDRESS,
        "value": value,
        "tokenSymbol": "USDC",
        "tokenDecimal": "18",
        "contractAddress": "0x" + "2" * 40,
        "timeStamp": "1700000000",
    }


def _ok(result) -> dict:
    return {"status": "1", "message": "OK", "result": result}


def _empty(message: str) -> dict:
    return {"status": "0", "message": message, "result": []}


@patch("enrichment.providers.evm.requests.get")
def test_run_computes_balance_and_tx_counts(get: Mock):
    get.side_effect = [
        _mock_response(_ok(str(5 * 10**18))),
        _mock_response(_ok([_tx("a" * 66)])),
        _mock_response(_ok([_token_transfer("b" * 66)])),
    ]

    result = evm.run(ADDRESS, "my-key")

    assert result["source"] == "evm"
    assert result["balance_wei"] == 5 * 10**18
    assert result["balance_eth"] == 5.0
    assert result["tx_count"] == 1
    assert result["recent_txs"] == ["a" * 66]
    assert result["token_transfer_count"] == 1
    assert result["recent_token_transfers"][0]["amount"] == 1.0
    assert result["recent_token_transfers"][0]["symbol"] == "USDC"
    assert result["last_seen"] == 1700000000


@patch("enrichment.providers.evm.requests.get")
def test_run_treats_no_transactions_found_as_empty_not_error(get: Mock):
    get.side_effect = [
        _mock_response(_ok("0")),
        _mock_response(_empty("No transactions found")),
        _mock_response(_empty("No token transfers found")),
    ]

    result = evm.run(ADDRESS, "my-key")

    assert "error" not in result
    assert result["tx_count"] == 0
    assert result["token_transfer_count"] == 0
    assert result["last_seen"] is None


@patch("enrichment.providers.evm.requests.get")
def test_run_requires_api_key(get: Mock):
    result = evm.run(ADDRESS, "")
    assert result["source"] == "evm"
    assert "error" in result
    assert "ETHERSCAN_API_KEY" in result["error"]
    get.assert_not_called()


@patch("enrichment.providers.evm.requests.get")
def test_run_rejects_wrong_chain_before_any_http_call(get: Mock):
    result = evm.run("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", "my-key")
    assert result["source"] == "evm"
    assert "error" in result
    get.assert_not_called()


@patch("enrichment.providers.evm.requests.get")
def test_run_rejects_ens_name(get: Mock):
    result = evm.run("vitalik.eth", "my-key")
    assert result["source"] == "evm"
    assert "error" in result
    assert "ENS" in result["error"]
    get.assert_not_called()


@patch("enrichment.providers.evm.requests.get")
def test_run_surfaces_invalid_key_error(get: Mock):
    get.return_value = _mock_response({"status": "0", "message": "Missing/Invalid API Key", "result": None})

    result = evm.run(ADDRESS, "bad-key")
    assert "error" in result
    assert "Missing/Invalid API Key" in result["error"]
    get.assert_called_once()


@patch("enrichment.providers.evm.requests.get")
def test_run_surfaces_http_error(get: Mock):
    get.return_value = _mock_response({}, status_code=503)

    result = evm.run(ADDRESS, "my-key")
    assert "error" in result
    assert "503" in result["error"]


@patch("enrichment.providers.evm.requests.get")
def test_run_stops_after_balance_error_without_querying_txlist(get: Mock):
    get.return_value = _mock_response({"status": "0", "message": "Invalid address format", "result": None})

    result = evm.run(ADDRESS, "my-key")
    assert "error" in result
    get.assert_called_once()


@patch("enrichment.providers.evm.requests.get")
def test_fetch_first_seen_returns_earliest_timestamp(get: Mock):
    get.return_value = _mock_response(_ok([_tx("a" * 66, timestamp="1443428683")]))

    result = evm.fetch_first_seen(ADDRESS, "my-key")

    assert result == 1443428683


@patch("enrichment.providers.evm.requests.get")
def test_fetch_first_seen_returns_none_for_genuinely_no_history(get: Mock):
    get.return_value = _mock_response(_empty("No transactions found"))

    result = evm.fetch_first_seen(ADDRESS, "my-key")

    assert result is None


@patch("enrichment.providers.evm.requests.get")
def test_fetch_first_seen_raises_on_real_api_error_instead_of_returning_none(get: Mock):
    # Etherscan's free-tier rate limit surfaces as status="0" message="NOTOK"
    # -- confirmed live 2026-07-02. This must NOT be conflated with "no
    # history" (which also has status="0" but a recognized empty message).
    get.return_value = _mock_response({"status": "0", "message": "NOTOK", "result": None})

    try:
        evm.fetch_first_seen(ADDRESS, "my-key")
        assert False, "expected fetch_first_seen to raise"
    except RuntimeError as exc:
        assert "NOTOK" in str(exc)


def test_summary_formats_success():
    payload = {"balance_eth": 5.0, "tx_count": 3, "token_transfer_count": 2}
    assert evm.summary(payload) == "evm balance=5.000000 ETH tx_count=3 token_transfers=2"


def test_summary_formats_error():
    payload = {"source": "evm", "error": "boom"}
    assert evm.summary(payload) == "evm error=boom"

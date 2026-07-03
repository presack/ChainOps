from unittest.mock import Mock, patch

from enrichment.providers import walletexplorer

ADDRESS = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"


def _mock_response(json_data=None, text="", status_code=200):
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


@patch("enrichment.providers.walletexplorer.requests.get")
def test_run_found_without_real_label(get: Mock):
    lookup_resp = _mock_response({"found": True, "wallet_id": "0bee64a8b1819ee9"})
    wallet_page_resp = _mock_response(text='<span class="wallet_name">[0bee64a8b1]</span>')
    get.side_effect = [lookup_resp, wallet_page_resp]

    result = walletexplorer.run(ADDRESS, "")

    assert result["found"] is True
    assert result["wallet_id"] == "0bee64a8b1819ee9"
    assert "label" not in result
    assert walletexplorer.summary(result) == "walletexplorer wallet=0bee64a8b1819ee9 (no label on record)"


@patch("enrichment.providers.walletexplorer.requests.get")
def test_run_found_with_real_label(get: Mock):
    lookup_resp = _mock_response({"found": True, "wallet_id": "abc123"})
    wallet_page_resp = _mock_response(text='<span class="wallet_name">MtGox.com</span>')
    get.side_effect = [lookup_resp, wallet_page_resp]

    result = walletexplorer.run(ADDRESS, "")

    assert result["label"] == "MtGox.com"
    assert walletexplorer.summary(result) == "walletexplorer wallet=abc123 label=MtGox.com"


@patch("enrichment.providers.walletexplorer.requests.get")
def test_run_not_found_skips_wallet_page_fetch(get: Mock):
    get.return_value = _mock_response({"found": False})

    result = walletexplorer.run(ADDRESS, "")

    assert result["found"] is False
    assert get.call_count == 1
    assert walletexplorer.summary(result) == "walletexplorer no cluster match (coverage is stale/pre-2018-biased)"


@patch("enrichment.providers.walletexplorer.requests.get")
def test_run_rejects_wrong_chain(get: Mock):
    result = walletexplorer.run("vitalik.eth", "")
    assert "error" in result
    get.assert_not_called()


@patch("enrichment.providers.walletexplorer.requests.get")
def test_run_rejects_non_address_btc_target(get: Mock):
    txid = "e" * 64
    result = walletexplorer.run(txid, "")
    assert "error" in result
    get.assert_not_called()


@patch("enrichment.providers.walletexplorer.requests.get")
def test_run_surfaces_http_error(get: Mock):
    get.return_value = _mock_response(status_code=503, text="down")
    result = walletexplorer.run(ADDRESS, "")
    assert "error" in result


@patch("enrichment.providers.walletexplorer.requests.get")
def test_run_degrades_gracefully_with_no_network(get: Mock):
    import requests as requests_module

    get.side_effect = requests_module.exceptions.ConnectionError("no route to host")

    result = walletexplorer.run(ADDRESS, "")
    assert "network error" in result["error"]


@patch("enrichment.providers.walletexplorer.requests.get")
def test_wallet_page_fetch_failure_is_non_fatal(get: Mock):
    lookup_resp = _mock_response({"found": True, "wallet_id": "abc123"})
    import requests as requests_module

    get.side_effect = [lookup_resp, requests_module.RequestException("timeout")]

    result = walletexplorer.run(ADDRESS, "")
    assert result["found"] is True
    assert "label" not in result

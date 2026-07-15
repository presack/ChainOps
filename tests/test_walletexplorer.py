from unittest.mock import Mock, patch

import pytest

from enrichment.providers import walletexplorer

ADDRESS = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"


_EMPTY_CSV = '"#Wallet x. Source: WalletExplorer.com"\r\ndate,received from,received amount,sent amount,sent to,balance,transaction\r\n'


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
    csv_resp = _mock_response(text=_EMPTY_CSV)
    get.side_effect = [lookup_resp, wallet_page_resp, csv_resp]

    result = walletexplorer.run(ADDRESS, "")

    assert result["found"] is True
    assert result["wallet_id"] == "0bee64a8b1819ee9"
    assert "label" not in result
    assert "known_counterparties" not in result
    assert walletexplorer.summary(result) == "walletexplorer wallet=0bee64a8b1819ee9 (no label on record)"


@patch("enrichment.providers.walletexplorer.requests.get")
def test_run_found_with_real_label_from_wallet_page_fallback(get: Mock):
    lookup_resp = _mock_response({"found": True, "wallet_id": "abc123"})
    wallet_page_resp = _mock_response(text='<span class="wallet_name">MtGox.com</span>')
    csv_resp = _mock_response(text=_EMPTY_CSV)
    get.side_effect = [lookup_resp, wallet_page_resp, csv_resp]

    result = walletexplorer.run(ADDRESS, "")

    assert result["label"] == "MtGox.com"
    assert walletexplorer.summary(result) == "walletexplorer wallet=abc123 label=MtGox.com"


@patch("enrichment.providers.walletexplorer.requests.get")
def test_run_uses_label_from_lookup_response_skips_wallet_page_fetch(get: Mock):
    lookup_resp = _mock_response({"found": True, "wallet_id": "000030860260d1a1", "label": "LocalBitcoins.com-old"})
    csv_resp = _mock_response(text=_EMPTY_CSV)
    get.side_effect = [lookup_resp, csv_resp]

    result = walletexplorer.run(ADDRESS, "")

    assert result["label"] == "LocalBitcoins.com-old"
    assert get.call_count == 2
    assert walletexplorer.summary(result) == "walletexplorer wallet=000030860260d1a1 label=LocalBitcoins.com-old"


@patch("enrichment.providers.walletexplorer.requests.get")
def test_run_surfaces_known_counterparties_from_tx_history(get: Mock):
    lookup_resp = _mock_response({"found": True, "wallet_id": "08af361778136202"})
    wallet_page_resp = _mock_response(text='<span class="wallet_name">[08af361778]</span>')
    csv_text = (
        '"#Wallet 08af361778136202. Source: WalletExplorer.com"\r\n'
        "date,received from,received amount,sent amount,sent to,balance,transaction\r\n"
        '2017-09-12 09:20:00,,,0.05,"Bittrex.com (00001f1606c30662)",0.001413,"tx1"\r\n'
        '2017-09-12 09:20:00,,,0.00086943,"(fee)",0.001413,"tx1"\r\n'
        '2013-03-16 18:01:00,"BTCGuild.com (000eadb78c11fb89)",0.1,,,4.100304,"tx2"\r\n'
        '2013-03-15 17:04:00,"BTCGuild.com (000eadb78c11fb89)",0.1,,,3.900304,"tx3"\r\n'
        '2013-03-01 23:45:07,"8b92bace7d1c0ddf",0.000304,,,0.000304,"tx4"\r\n'
    )
    csv_resp = _mock_response(text=csv_text)
    get.side_effect = [lookup_resp, wallet_page_resp, csv_resp]

    result = walletexplorer.run(ADDRESS, "")

    counterparties = {c["label"]: c for c in result["known_counterparties"]}
    assert set(counterparties) == {"Bittrex.com", "BTCGuild.com"}
    assert counterparties["Bittrex.com"] == {
        "label": "Bittrex.com",
        "wallet_id": "00001f1606c30662",
        "count": 1,
        "total_btc": 0.05,
        "first_seen": "2017-09-12 09:20:00",
        "last_seen": "2017-09-12 09:20:00",
    }
    assert counterparties["BTCGuild.com"]["count"] == 2
    assert counterparties["BTCGuild.com"]["total_btc"] == pytest.approx(0.2)
    assert counterparties["BTCGuild.com"]["first_seen"] == "2013-03-15 17:04:00"
    assert counterparties["BTCGuild.com"]["last_seen"] == "2013-03-16 18:01:00"
    assert "2 known counterparties in history" in walletexplorer.summary(result)


@patch("enrichment.providers.walletexplorer.requests.get")
def test_known_counterparties_fetch_failure_is_non_fatal(get: Mock):
    lookup_resp = _mock_response({"found": True, "wallet_id": "abc123", "label": "SomeExchange"})
    import requests as requests_module

    get.side_effect = [lookup_resp, requests_module.RequestException("timeout")]

    result = walletexplorer.run(ADDRESS, "")

    assert result["label"] == "SomeExchange"
    assert "known_counterparties" not in result


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

    get.side_effect = [lookup_resp, requests_module.RequestException("timeout"), requests_module.RequestException("timeout")]

    result = walletexplorer.run(ADDRESS, "")
    assert result["found"] is True
    assert "label" not in result
    assert "known_counterparties" not in result

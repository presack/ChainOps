from unittest.mock import Mock, patch

from enrichment.providers import price


@patch("enrichment.providers.price.requests.get")
def test_run_returns_current_usd_price(get: Mock):
    get.return_value = Mock(status_code=200)
    get.return_value.json.return_value = {"bitcoin": {"usd": 61213}}

    result = price.run("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", "")

    assert result["source"] == "price"
    assert result["coin_id"] == "bitcoin"
    assert result["usd"] == 61213
    get.assert_called_once()
    assert get.call_args.kwargs["params"] == {"ids": "bitcoin", "vs_currencies": "usd"}


@patch("enrichment.providers.price.requests.get")
def test_run_maps_ethereum_chain(get: Mock):
    get.return_value = Mock(status_code=200)
    get.return_value.json.return_value = {"ethereum": {"usd": 3400}}

    result = price.run("vitalik.eth", "")
    assert result["coin_id"] == "ethereum"
    assert result["usd"] == 3400


def test_run_rejects_invalid_target():
    result = price.run("not-a-real-target!!", "")
    assert "error" in result


@patch("enrichment.providers.price.requests.get")
def test_run_surfaces_http_error(get: Mock):
    get.return_value = Mock(status_code=500, text="boom")
    result = price.run("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", "")
    assert "error" in result


@patch("enrichment.providers.price.requests.get")
def test_run_degrades_gracefully_with_no_network(get: Mock):
    import requests as requests_module

    get.side_effect = requests_module.exceptions.ConnectionError("no route to host")
    result = price.run("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", "")
    assert "network error" in result["error"]


def test_summary_formats_success():
    assert price.summary({"coin_id": "bitcoin", "usd": 61213}) == "price bitcoin = $61,213"


def test_summary_formats_error():
    assert price.summary({"error": "boom"}) == "price error=boom"


@patch("enrichment.providers.price.requests.get")
def test_price_at_timestamp_returns_historical_usd(get: Mock):
    get.return_value = Mock(status_code=200)
    get.return_value.json.return_value = {"market_data": {"current_price": {"usd": 17800}}}

    result = price.price_at_timestamp("bitcoin", 1605600000)

    assert result["usd"] == 17800
    assert result["date"] == "17-11-2020"


@patch("enrichment.providers.price.requests.get")
def test_price_at_timestamp_surfaces_free_tier_range_limit(get: Mock):
    get.return_value = Mock(status_code=400)
    get.return_value.json.return_value = {
        "error": {"status": {"error_code": 10012, "error_message": "exceeds the allowed time range"}}
    }

    result = price.price_at_timestamp("bitcoin", 1605600000)

    assert "error" in result
    assert "365 days" in result["error"]


def test_price_at_timestamp_rejects_unmapped_chain():
    result = price.price_at_timestamp("dogecoin", 1605600000)
    assert "error" in result

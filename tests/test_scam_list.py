import importlib
from unittest.mock import Mock, patch

from enrichment.providers import scam_list

SCAM_ADDR = "0x101ce0cedd142f199c9ef61739ae59b6611a0fc0"
CLEAN_ADDR = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
TRON_ADDR = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"  # actually BTC, used to exercise the non-EVM path


def _reload_at(monkeypatch, tmp_path):
    monkeypatch.setenv("SCAM_LIST_CACHE_PATH", str(tmp_path / "scam_list_addresses.json"))
    importlib.reload(scam_list)
    return scam_list


@patch("enrichment.providers.scam_list.requests.get")
def test_refresh_downloads_parses_and_caches(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200)
    get.return_value.raise_for_status = Mock()
    get.return_value.json.return_value = [SCAM_ADDR]

    payload = mod.refresh()

    assert payload["addresses"] == [SCAM_ADDR]
    assert (tmp_path / "scam_list_addresses.json").exists()


@patch("enrichment.providers.scam_list.requests.get")
def test_load_addresses_downloads_once_then_uses_cache(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200)
    get.return_value.raise_for_status = Mock()
    get.return_value.json.return_value = [SCAM_ADDR]

    first = mod.load_addresses()
    second = mod.load_addresses()

    assert first == second
    get.assert_called_once()


@patch("enrichment.providers.scam_list.requests.get")
def test_run_flags_exact_match(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200)
    get.return_value.raise_for_status = Mock()
    get.return_value.json.return_value = [SCAM_ADDR]

    result = mod.run(SCAM_ADDR, "")
    assert result["checked"] is True
    assert result["flagged"] is True
    assert mod.summary(result) == "scam_list FLAGGED"


@patch("enrichment.providers.scam_list.requests.get")
def test_run_reports_no_match(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200)
    get.return_value.raise_for_status = Mock()
    get.return_value.json.return_value = [SCAM_ADDR]

    result = mod.run(CLEAN_ADDR, "")
    assert result["checked"] is True
    assert result["flagged"] is False
    assert mod.summary(result) == "scam_list no match"


def test_run_reports_unsupported_for_non_evm_chain(monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    result = mod.run(TRON_ADDR, "")
    assert result["checked"] is False
    assert "EVM only" in result["error"]


@patch("enrichment.providers.scam_list.requests.get")
def test_run_degrades_gracefully_when_download_fails(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.side_effect = ConnectionError("network unreachable")

    result = mod.run(CLEAN_ADDR, "")
    assert result["checked"] is False
    assert "unavailable" in result["error"]
    assert mod.summary(result).startswith("scam_list error=")


# --- check_addresses (batch lookup, used by graph.py) ---


@patch("enrichment.providers.scam_list.requests.get")
def test_check_addresses_flags_only_listed_ones(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200)
    get.return_value.raise_for_status = Mock()
    get.return_value.json.return_value = [SCAM_ADDR]

    result = mod.check_addresses([SCAM_ADDR, CLEAN_ADDR], "ethereum")

    assert result == {SCAM_ADDR: True, CLEAN_ADDR: False}


def test_check_addresses_non_evm_chain_returns_all_false():
    result = scam_list.check_addresses(["addr1", "addr2"], "bitcoin")
    assert result == {"addr1": False, "addr2": False}


@patch("enrichment.providers.scam_list.load_addresses", side_effect=RuntimeError("network down"))
def test_check_addresses_degrades_gracefully_when_cache_unavailable(load):
    result = scam_list.check_addresses(["addr1"], "ethereum")
    assert result == {"addr1": False}

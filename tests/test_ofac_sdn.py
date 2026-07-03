import importlib
from unittest.mock import Mock, patch

from enrichment.providers import ofac_sdn

# Minimal fixture matching the verified real sdn_advanced.xml schema:
# ReferenceValueSets/FeatureTypeValues/FeatureType (ID + "Digital Currency
# Address - <ASSET>" text) and //Feature[@FeatureTypeID]/FeatureVersion/
# VersionDetail (the address text).
_FAKE_SDN_XML = """<?xml version="1.0" encoding="utf-8"?>
<Sanctions xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ADVANCED_XML">
  <ReferenceValueSets>
    <FeatureTypeValues>
      <FeatureType ID="344" FeatureTypeGroupID="1">Digital Currency Address - XBT</FeatureType>
      <FeatureType ID="345" FeatureTypeGroupID="1">Digital Currency Address - ETH</FeatureType>
    </FeatureTypeValues>
  </ReferenceValueSets>
  <DistinctParties>
    <DistinctParty>
      <Profile>
        <Feature ID="1" FeatureTypeID="344">
          <FeatureVersion ID="1" ReliabilityID="1">
            <VersionDetail DetailTypeID="1432">1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa</VersionDetail>
          </FeatureVersion>
        </Feature>
        <Feature ID="2" FeatureTypeID="344">
          <FeatureVersion ID="2" ReliabilityID="1">
            <VersionDetail DetailTypeID="1432">1AnotherSanctionedBTCAddressXXXX</VersionDetail>
          </FeatureVersion>
        </Feature>
        <Feature ID="3" FeatureTypeID="345">
          <FeatureVersion ID="3" ReliabilityID="1">
            <VersionDetail DetailTypeID="1432">0xSanctionedEthAddress</VersionDetail>
          </FeatureVersion>
        </Feature>
      </Profile>
    </DistinctParty>
  </DistinctParties>
</Sanctions>
""".encode("utf-8")


def _reload_at(monkeypatch, tmp_path):
    monkeypatch.setenv("OFAC_SDN_CACHE_PATH", str(tmp_path / "ofac_sdn_addresses.json"))
    importlib.reload(ofac_sdn)
    return ofac_sdn


def test_extract_addresses_from_xml():
    result = ofac_sdn.extract_addresses(_FAKE_SDN_XML, ["XBT", "ETH"])
    assert result["XBT"] == ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "1AnotherSanctionedBTCAddressXXXX"]
    assert result["ETH"] == ["0xSanctionedEthAddress"]


def test_extract_addresses_unknown_asset_code_returns_empty_list():
    result = ofac_sdn.extract_addresses(_FAKE_SDN_XML, ["TRX"])
    assert result["TRX"] == []


@patch("enrichment.providers.ofac_sdn.requests.get")
def test_refresh_downloads_parses_and_caches(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200, content=_FAKE_SDN_XML)
    get.return_value.raise_for_status = Mock()

    payload = mod.refresh(["XBT"])

    assert payload["addresses"]["XBT"] == ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "1AnotherSanctionedBTCAddressXXXX"]
    assert (tmp_path / "ofac_sdn_addresses.json").exists()


@patch("enrichment.providers.ofac_sdn.requests.get")
def test_load_addresses_downloads_once_then_uses_cache(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200, content=_FAKE_SDN_XML)
    get.return_value.raise_for_status = Mock()

    first = mod.load_addresses()
    second = mod.load_addresses()

    assert first == second
    get.assert_called_once()


@patch("enrichment.providers.ofac_sdn.requests.get")
def test_run_flags_exact_match(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200, content=_FAKE_SDN_XML)
    get.return_value.raise_for_status = Mock()

    result = mod.run("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "")
    assert result["checked"] is True
    assert result["sanctioned"] is True
    assert mod.summary(result) == "ofac_sdn SANCTIONED MATCH"


@patch("enrichment.providers.ofac_sdn.requests.get")
def test_run_reports_no_match(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200, content=_FAKE_SDN_XML)
    get.return_value.raise_for_status = Mock()

    result = mod.run("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", "")
    assert result["checked"] is True
    assert result["sanctioned"] is False
    assert mod.summary(result) == "ofac_sdn no match"


def test_run_rejects_unsupported_chain(monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    from core_ops import ClassifiedTarget

    fake = ClassifiedTarget(target="doge1abc", chain="dogecoin", target_type="doge_address", valid=True)
    with patch("enrichment.providers.ofac_sdn.classify_target", return_value=fake):
        result = mod.run("doge1abc", "")
    assert result["source"] == "ofac_sdn"
    assert "error" in result


@patch("enrichment.providers.ofac_sdn.requests.get")
def test_run_degrades_gracefully_when_download_fails(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.side_effect = ConnectionError("network unreachable")

    result = mod.run("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", "")
    assert result["checked"] is False
    assert "unavailable" in result["error"]
    assert mod.summary(result).startswith("ofac_sdn error=")


# --- check_addresses (batch lookup, used by graph.py) ---


@patch("enrichment.providers.ofac_sdn.requests.get")
def test_check_addresses_flags_only_sanctioned_ones(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200, content=_FAKE_SDN_XML)
    get.return_value.raise_for_status = Mock()

    result = mod.check_addresses(
        ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"], "bitcoin"
    )

    assert result == {
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa": True,
        "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a": False,
    }


@patch("enrichment.providers.ofac_sdn.requests.get")
def test_check_addresses_only_loads_cache_once_for_the_whole_batch(get: Mock, monkeypatch, tmp_path):
    mod = _reload_at(monkeypatch, tmp_path)
    get.return_value = Mock(status_code=200, content=_FAKE_SDN_XML)
    get.return_value.raise_for_status = Mock()

    mod.check_addresses(["addr1", "addr2", "addr3"], "bitcoin")

    get.assert_called_once()


def test_check_addresses_unsupported_chain_returns_all_false():
    result = ofac_sdn.check_addresses(["addr1", "addr2"], "dogecoin")
    assert result == {"addr1": False, "addr2": False}


@patch("enrichment.providers.ofac_sdn.load_addresses", side_effect=RuntimeError("network down"))
def test_check_addresses_degrades_gracefully_when_cache_unavailable(load):
    result = ofac_sdn.check_addresses(["addr1"], "bitcoin")
    assert result == {"addr1": False}

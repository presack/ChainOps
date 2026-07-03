import importlib

import keystore
from enrichment.providers import _registry


def _reload_at(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAINOPS_KEYS_DIR", str(tmp_path))
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    monkeypatch.delenv("TRONGRID_API_KEY", raising=False)
    importlib.reload(keystore)
    importlib.reload(_registry)
    return _registry


def test_key_providers_has_evm_required_and_tron_optional():
    assert _registry.KEY_PROVIDERS["evm"].required is True
    assert _registry.KEY_PROVIDERS["evm"].env_var == "ETHERSCAN_API_KEY"
    assert _registry.KEY_PROVIDERS["tron"].required is False
    assert _registry.KEY_PROVIDERS["tron"].env_var == "TRONGRID_API_KEY"


def test_get_key_status_reports_missing_when_unset(monkeypatch, tmp_path):
    reg = _reload_at(monkeypatch, tmp_path)
    status = reg.get_key_status("evm")
    assert status["configured"] is False
    assert status["masked"] == ""


def test_get_key_status_reports_configured_and_masked(monkeypatch, tmp_path):
    reg = _reload_at(monkeypatch, tmp_path)
    keystore.set_key("ETHERSCAN_API_KEY", "abcd1234wxyz")
    status = reg.get_key_status("evm")
    assert status["configured"] is True
    assert status["masked"] == keystore.mask("abcd1234wxyz")


def test_get_all_status_covers_every_registered_provider(monkeypatch, tmp_path):
    reg = _reload_at(monkeypatch, tmp_path)
    result = reg.get_all_status()
    assert set(result.keys()) == set(reg.KEY_PROVIDERS.keys())

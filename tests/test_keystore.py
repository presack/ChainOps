import importlib
from unittest.mock import patch

import keystore


def _reload_keystore_at(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAINOPS_KEYS_DIR", str(tmp_path))
    monkeypatch.delenv("SOME_API_KEY", raising=False)
    importlib.reload(keystore)
    return keystore


def test_set_key_then_get_key_roundtrips(monkeypatch, tmp_path):
    ks = _reload_keystore_at(monkeypatch, tmp_path)
    ks.set_key("SOME_API_KEY", "abc123")
    assert ks.get_key("SOME_API_KEY") == "abc123"
    assert (tmp_path / "keys.env").exists()


def test_get_key_missing_returns_empty_string(monkeypatch, tmp_path):
    ks = _reload_keystore_at(monkeypatch, tmp_path)
    assert ks.get_key("NOT_SET_KEY") == ""


def test_delete_key_clears_value(monkeypatch, tmp_path):
    ks = _reload_keystore_at(monkeypatch, tmp_path)
    ks.set_key("SOME_API_KEY", "abc123")
    ks.delete_key("SOME_API_KEY")
    assert ks.get_key("SOME_API_KEY") == ""


def test_load_into_environ_does_not_override_existing_env(monkeypatch, tmp_path):
    ks = _reload_keystore_at(monkeypatch, tmp_path)
    ks.set_key("SOME_API_KEY", "from-file")
    monkeypatch.setenv("SOME_API_KEY", "from-env")
    ks.load_into_environ()
    assert keystore.os.environ["SOME_API_KEY"] == "from-env"


def test_sync_into_environ_overwrites_existing_env(monkeypatch, tmp_path):
    ks = _reload_keystore_at(monkeypatch, tmp_path)
    ks.set_key("SOME_API_KEY", "from-file")
    monkeypatch.setenv("SOME_API_KEY", "stale-value")
    ks.sync_into_environ()
    assert keystore.os.environ["SOME_API_KEY"] == "from-file"


def test_mask_short_value():
    assert keystore.mask("ab") == "••••"


def test_mask_long_value_keeps_last_four():
    assert keystore.mask("abcdefgh1234") == "••••••••1234"


def test_mask_empty_value():
    assert keystore.mask("") == ""


def _fake_provider(name, required):
    from enrichment.providers._registry import KeyProvider

    return KeyProvider(name, f"{name.upper()} Provider", f"{name.upper()}_KEY", "some address", required)


def test_run_setup_wizard_saves_entered_keys(monkeypatch, tmp_path, capsys):
    ks = _reload_keystore_at(monkeypatch, tmp_path)
    monkeypatch.delenv("EVM_KEY", raising=False)
    monkeypatch.delenv("TRON_KEY", raising=False)
    fake_providers = {"evm": _fake_provider("evm", True), "tron": _fake_provider("tron", False)}
    with (
        patch("enrichment.providers._registry.KEY_PROVIDERS", fake_providers),
        patch("builtins.input", side_effect=["new-evm-key", "new-tron-key"]),
    ):
        ks.run_setup_wizard()

    assert ks.get_key("EVM_KEY") == "new-evm-key"
    assert ks.get_key("TRON_KEY") == "new-tron-key"
    assert "2 key(s) saved" in capsys.readouterr().out


def test_run_setup_wizard_done_stops_early_without_saving_rest(monkeypatch, tmp_path, capsys):
    ks = _reload_keystore_at(monkeypatch, tmp_path)
    monkeypatch.delenv("EVM_KEY", raising=False)
    monkeypatch.delenv("TRON_KEY", raising=False)
    fake_providers = {"evm": _fake_provider("evm", True), "tron": _fake_provider("tron", False)}
    with (
        patch("enrichment.providers._registry.KEY_PROVIDERS", fake_providers),
        patch("builtins.input", side_effect=["done"]),
    ):
        ks.run_setup_wizard()

    assert ks.get_key("EVM_KEY") == ""
    assert ks.get_key("TRON_KEY") == ""
    assert "No changes made" in capsys.readouterr().out


def test_run_setup_wizard_blank_input_keeps_existing_value(monkeypatch, tmp_path):
    ks = _reload_keystore_at(monkeypatch, tmp_path)
    monkeypatch.delenv("EVM_KEY", raising=False)
    ks.set_key("EVM_KEY", "already-set")
    fake_providers = {"evm": _fake_provider("evm", True)}
    with (
        patch("enrichment.providers._registry.KEY_PROVIDERS", fake_providers),
        patch("builtins.input", side_effect=[""]),
    ):
        ks.run_setup_wizard()

    assert ks.get_key("EVM_KEY") == "already-set"

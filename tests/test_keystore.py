import importlib

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

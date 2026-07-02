import importlib
import time

import cache


def _reload_cache_at(monkeypatch, tmp_path):
    db_path = str(tmp_path / "cache" / "chainops.db")
    monkeypatch.setenv("CACHE_PATH", db_path)
    importlib.reload(cache)
    return cache


def test_put_then_get_roundtrips(monkeypatch, tmp_path):
    c = _reload_cache_at(monkeypatch, tmp_path)
    c.put("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", "blockstream", {"balance_sats": 1000})

    result = c.get("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", "blockstream")
    assert result is not None
    payload, fetched_at = result
    assert payload == {"balance_sats": 1000}
    assert fetched_at <= int(time.time())


def test_get_is_case_insensitive_on_target(monkeypatch, tmp_path):
    c = _reload_cache_at(monkeypatch, tmp_path)
    c.put("1933PhfhK3ZgFQNLGSDXvqCn32k2buXY8a", "blockstream", {"ok": True})
    assert c.get("1933phfhk3zgfqnlgsdxvqcn32k2buxy8a", "blockstream") is not None


def test_get_miss_returns_none(monkeypatch, tmp_path):
    c = _reload_cache_at(monkeypatch, tmp_path)
    assert c.get("nonexistent", "blockstream") is None


def test_get_expires_with_finite_ttl(monkeypatch, tmp_path):
    c = _reload_cache_at(monkeypatch, tmp_path)
    c.put("addr", "scope", {"v": 1})
    assert c.get("addr", "scope", ttl=0) is None


def test_get_with_ttl_none_never_expires(monkeypatch, tmp_path):
    c = _reload_cache_at(monkeypatch, tmp_path)
    c.put("some-confirmed-txid", "blockstream_tx", {"confirmed": True})
    result = c.get("some-confirmed-txid", "blockstream_tx", ttl=None)
    assert result is not None
    assert result[0] == {"confirmed": True}


def test_different_scopes_are_independent(monkeypatch, tmp_path):
    c = _reload_cache_at(monkeypatch, tmp_path)
    c.put("addr", "blockstream", {"source": "blockstream"})
    c.put("addr", "price", {"source": "price"})
    assert c.get("addr", "blockstream")[0] == {"source": "blockstream"}
    assert c.get("addr", "price")[0] == {"source": "price"}


def test_sweep_removes_old_entries(monkeypatch, tmp_path):
    c = _reload_cache_at(monkeypatch, tmp_path)
    c.put("addr", "scope", {"v": 1})

    conn = c._open()
    try:
        conn.execute("UPDATE result_cache SET fetched_at = 0")
        conn.commit()
    finally:
        conn.close()

    c.sweep()
    assert c.get("addr", "scope", ttl=None) is None

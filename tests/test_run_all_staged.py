from unittest.mock import patch

from core_ops import run_all_staged

ADDRESS = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"


def _patch_providers(**overrides):
    defaults = dict(
        blockstream_run={"source": "blockstream", "balance_sats": 100, "tx_count": 2},
        price_run={"source": "price", "usd": 61000},
        walletexplorer_run={"source": "walletexplorer", "found": False},
        ofac_run={"source": "ofac_sdn", "checked": True, "sanctioned": False},
        fetch_tx_history=[
            {"txid": "a", "status": {"confirmed": True, "block_time": 1000}},
            {"txid": "b", "status": {"confirmed": True, "block_time": 5000}},
            {"txid": "c", "status": {"confirmed": False}},
        ],
    )
    defaults.update(overrides)
    return (
        patch("enrichment.providers.blockstream.run", return_value=defaults["blockstream_run"]),
        patch("enrichment.providers.price.run", return_value=defaults["price_run"]),
        patch("enrichment.providers.walletexplorer.run", return_value=defaults["walletexplorer_run"]),
        patch("enrichment.providers.ofac_sdn.run", return_value=defaults["ofac_run"]),
        patch("enrichment.providers.blockstream.fetch_tx_history", return_value=defaults["fetch_tx_history"]),
    )


def test_run_all_staged_combines_all_providers():
    patches = _patch_providers()
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        result = run_all_staged(ADDRESS)

    assert result["target"] == ADDRESS
    assert result["chain"] == "bitcoin"
    assert result["valid"] is True
    assert result["blockstream"]["balance_sats"] == 100
    assert result["price"]["usd"] == 61000
    assert result["walletexplorer"]["found"] is False
    assert result["ofac_sdn"]["sanctioned"] is False
    assert result["first_seen"] == 1000
    assert result["last_seen"] == 5000
    assert result["dormancy_days"] is not None


def test_run_all_staged_rejects_invalid_target():
    result = run_all_staged("not-a-real-target!!")
    assert result["valid"] is False
    assert "error" in result
    assert "blockstream" not in result


def test_run_all_staged_rejects_non_btc_target():
    result = run_all_staged("vitalik.eth")
    assert result["valid"] is True
    assert "error" in result
    assert "blockstream" not in result


def test_run_all_staged_rejects_non_address_btc_target():
    txid = "f" * 64
    result = run_all_staged(txid)
    assert "error" in result
    assert "blockstream" not in result


def test_run_all_staged_skips_tx_history_when_blockstream_errors():
    patches = _patch_providers(blockstream_run={"source": "blockstream", "error": "boom"})
    with patches[0], patches[1], patches[2], patches[3], patches[4] as fetch_mock:
        result = run_all_staged(ADDRESS)

    assert "error" in result["blockstream"]
    assert "first_seen" not in result
    fetch_mock.assert_not_called()


def test_run_all_staged_handles_no_confirmed_txs():
    patches = _patch_providers(fetch_tx_history=[{"txid": "a", "status": {"confirmed": False}}])
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        result = run_all_staged(ADDRESS)

    assert result["first_seen"] is None
    assert result["last_seen"] is None
    assert result["dormancy_days"] is None


def test_run_all_staged_degrades_gracefully_on_tx_history_failure():
    patches = list(_patch_providers())
    with patches[0], patches[1], patches[2], patches[3]:
        with patch("enrichment.providers.blockstream.fetch_tx_history", side_effect=ConnectionError("down")):
            result = run_all_staged(ADDRESS)

    assert "tx_history_error" in result
    assert "first_seen" not in result


def test_run_all_staged_emits_progressive_snapshots():
    patches = _patch_providers()
    snapshots = []
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        run_all_staged(ADDRESS, on_update=snapshots.append)

    assert len(snapshots) >= 5
    assert "blockstream" not in snapshots[0]
    assert "blockstream" in snapshots[-1]
    assert "dormancy_days" in snapshots[-1]


def test_run_all_staged_on_update_exception_is_swallowed():
    patches = _patch_providers()

    def bad_callback(_snapshot):
        raise RuntimeError("boom")

    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        result = run_all_staged(ADDRESS, on_update=bad_callback)

    assert result["target"] == ADDRESS

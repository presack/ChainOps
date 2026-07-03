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


def test_run_all_staged_rejects_still_unsupported_target():
    # Block height classifies fine but has no staged handler (unlike BTC
    # address/Tron address/ETH address/ENS name, which all do).
    result = run_all_staged("700000")
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


TRON_ADDRESS = "TXFBqBbqJommqZf7BV8NNYzePh97UmJodJ"


def _patch_tron_providers(**overrides):
    defaults = dict(
        tron_run={
            "source": "tron",
            "balance_trx": 5.0,
            "activated": True,
            "usdt_transfer_count": 2,
            "recent_usdt_transfers": [],
        },
        price_run={"source": "price", "usd": 0.12},
        ofac_run={"source": "ofac_sdn", "checked": True, "sanctioned": False},
        fetch_usdt_transfer_history=[
            {"block_timestamp": 1_700_000_000_000},
            {"block_timestamp": 1_700_005_000_000},
        ],
    )
    defaults.update(overrides)
    return (
        patch("enrichment.providers.tron.run", return_value=defaults["tron_run"]),
        patch("enrichment.providers.price.run", return_value=defaults["price_run"]),
        patch("enrichment.providers.ofac_sdn.run", return_value=defaults["ofac_run"]),
        patch(
            "enrichment.providers.tron.fetch_usdt_transfer_history",
            return_value=defaults["fetch_usdt_transfer_history"],
        ),
    )


def test_run_all_staged_combines_tron_providers():
    patches = _patch_tron_providers()
    with patches[0], patches[1], patches[2], patches[3]:
        result = run_all_staged(TRON_ADDRESS)

    assert result["target"] == TRON_ADDRESS
    assert result["chain"] == "tron"
    assert result["valid"] is True
    assert result["tron"]["balance_trx"] == 5.0
    assert result["price"]["usd"] == 0.12
    assert result["ofac_sdn"]["sanctioned"] is False
    assert result["first_seen"] == 1_700_000_000
    assert result["last_seen"] == 1_700_005_000
    assert result["dormancy_days"] is not None


def test_run_all_staged_skips_transfer_history_when_tron_errors():
    patches = _patch_tron_providers(tron_run={"source": "tron", "error": "boom"})
    with patches[0], patches[1], patches[2], patches[3] as fetch_mock:
        result = run_all_staged(TRON_ADDRESS)

    assert "error" in result["tron"]
    assert "first_seen" not in result
    fetch_mock.assert_not_called()


def test_run_all_staged_passes_trongrid_key_from_keystore():
    patches = _patch_tron_providers()
    with (
        patch("keystore.get_key", return_value="test-trongrid-key"),
        patches[0] as run_mock,
        patches[1],
        patches[2],
        patches[3] as fetch_mock,
    ):
        run_all_staged(TRON_ADDRESS)

    run_mock.assert_called_once_with(TRON_ADDRESS, "test-trongrid-key")
    fetch_mock.assert_called_once_with(TRON_ADDRESS, "test-trongrid-key")


def test_run_all_staged_degrades_gracefully_on_tron_history_failure():
    patches = list(_patch_tron_providers())
    with patches[0], patches[1], patches[2]:
        with patch(
            "enrichment.providers.tron.fetch_usdt_transfer_history",
            side_effect=ConnectionError("down"),
        ):
            result = run_all_staged(TRON_ADDRESS)

    assert "tx_history_error" in result
    assert "first_seen" not in result


ENS_NAME = "vitalik.eth"
RESOLVED_ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"


def _patch_evm_providers(**overrides):
    defaults = dict(
        evm_run={
            "source": "evm",
            "balance_eth": 5.0,
            "tx_count": 3,
            "token_transfer_count": 1,
            "last_seen": 1_700_005_000,
        },
        price_run={"source": "price", "usd": 1700.0},
        ofac_run={"source": "ofac_sdn", "checked": True, "sanctioned": False},
        fetch_first_seen=1_700_000_000,
        tag_address={"kind": "eoa", "delegate_address": None, "contract_name": None, "error": None},
    )
    defaults.update(overrides)
    return (
        patch("enrichment.providers.evm.run", return_value=defaults["evm_run"]),
        patch("enrichment.providers.price.run", return_value=defaults["price_run"]),
        patch("enrichment.providers.ofac_sdn.run", return_value=defaults["ofac_run"]),
        patch("enrichment.providers.evm.fetch_first_seen", return_value=defaults["fetch_first_seen"]),
        patch("enrichment.providers.contract_info.tag_address", return_value=defaults["tag_address"]),
    )


def test_run_all_staged_resolves_ens_name_then_runs_evm_query():
    patches = _patch_evm_providers()
    with (
        patch("keystore.get_key", return_value="test-etherscan-key"),
        patch("enrichment.providers.ens.resolve_ens", return_value={"address": RESOLVED_ADDRESS, "error": None}),
        patches[0] as evm_run_mock,
        patches[1],
        patches[2],
        patches[3],
        patches[4],
    ):
        result = run_all_staged(ENS_NAME)

    assert result["target"] == ENS_NAME
    assert result["resolved_address"] == RESOLVED_ADDRESS
    assert result["chain"] == "ethereum"
    assert result["target_type"] == "ens_name"
    assert "error" not in result
    assert result["evm"]["balance_eth"] == 5.0
    evm_run_mock.assert_called_once_with(RESOLVED_ADDRESS, "test-etherscan-key")


def test_run_all_staged_surfaces_ens_resolution_error():
    with patch(
        "enrichment.providers.ens.resolve_ens",
        return_value={"address": None, "error": "'vitalik.eth' has no resolver set (likely unregistered)"},
    ):
        result = run_all_staged(ENS_NAME)

    assert result["target"] == ENS_NAME
    assert "resolved_address" not in result
    assert result["error"] == "'vitalik.eth' has no resolver set (likely unregistered)"
    assert "evm" not in result


def test_run_all_staged_combines_evm_providers_for_direct_address():
    patches = _patch_evm_providers()
    with (
        patch("keystore.get_key", return_value="test-etherscan-key"),
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
    ):
        result = run_all_staged(RESOLVED_ADDRESS)

    assert result["target"] == RESOLVED_ADDRESS
    assert "resolved_address" not in result
    assert result["chain"] == "ethereum"
    assert result["evm"]["balance_eth"] == 5.0
    assert result["price"]["usd"] == 1700.0
    assert result["contract_info"]["kind"] == "eoa"
    assert result["first_seen"] == 1_700_000_000
    assert result["last_seen"] == 1_700_005_000
    assert result["dormancy_days"] is not None


def test_run_all_staged_surfaces_evm_rate_limit_as_tx_history_error_not_silent_none():
    # Regression test: evm.fetch_first_seen used to swallow Etherscan's
    # rate-limit response ("NOTOK") into a silent None indistinguishable
    # from "no history" -- confirmed live 2026-07-02. It must now raise
    # and be caught here, same contract as tron.fetch_usdt_transfer_history.
    patches = _patch_evm_providers()
    with (
        patch("keystore.get_key", return_value="test-etherscan-key"),
        patches[0],
        patches[1],
        patches[2],
        patches[4],
        patch("enrichment.providers.evm.fetch_first_seen", side_effect=RuntimeError("first-seen lookup failed: NOTOK")),
    ):
        result = run_all_staged(RESOLVED_ADDRESS)

    assert "tx_history_error" in result
    assert "NOTOK" in result["tx_history_error"]
    assert "first_seen" not in result

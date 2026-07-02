import csv
from unittest.mock import patch

from bulk import (
    TRIAGE_FIELDNAMES,
    read_addresses_csv,
    run_bulk_triage,
    triage_addresses,
    write_triage_csv,
)

ADDR_A = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"
ADDR_B = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"


def _staged(target, **overrides):
    base = {
        "target": target,
        "chain": "bitcoin",
        "target_type": "btc_address_p2pkh",
        "valid": True,
        "blockstream": {"balance_btc": 0.001, "balance_sats": 100000, "tx_count": 5},
        "price": {"usd": 60000},
        "walletexplorer": {"found": True, "wallet_id": "wallet123"},
        "ofac_sdn": {"checked": True, "sanctioned": False},
        "first_seen": 1000,
        "last_seen": 2000,
        "dormancy_days": 10.0,
    }
    base.update(overrides)
    return base


# --- read_addresses_csv ---


def test_read_addresses_csv_header_mode(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("address,note\n" + ADDR_A + ",flagged\n" + ADDR_B + ",\n")
    result = read_addresses_csv(str(path))
    assert result == [ADDR_A, ADDR_B]


def test_read_addresses_csv_bare_column_mode(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text(ADDR_A + "\n" + ADDR_B + "\n")
    result = read_addresses_csv(str(path))
    assert result == [ADDR_A, ADDR_B]


def test_read_addresses_csv_skips_blank_lines(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text(ADDR_A + "\n\n" + ADDR_B + "\n")
    result = read_addresses_csv(str(path))
    assert result == [ADDR_A, ADDR_B]


def test_read_addresses_csv_empty_file(tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("")
    assert read_addresses_csv(str(path)) == []


# --- triage_addresses ---


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_triage_produces_one_row_per_address_in_order(mock_run, mock_fetch):
    mock_run.side_effect = lambda addr: _staged(addr)
    mock_fetch.return_value = []

    rows = triage_addresses([ADDR_A, ADDR_B])

    assert [r["address"] for r in rows] == [ADDR_A, ADDR_B]
    assert set(rows[0].keys()) == set(TRIAGE_FIELDNAMES)


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_triage_invalid_address_gets_error_row(mock_run, mock_fetch):
    mock_run.return_value = {"valid": False, "error": "unrecognized target format"}
    mock_fetch.return_value = []

    rows = triage_addresses(["garbage!!"])

    assert rows[0]["valid"] is False
    assert rows[0]["error"] == "unrecognized target format"
    assert rows[0]["balance_btc"] == ""
    mock_fetch.assert_not_called()


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_triage_copies_core_fields_from_staged_result(mock_run, mock_fetch):
    mock_run.return_value = _staged(ADDR_A)
    mock_fetch.return_value = []

    row = triage_addresses([ADDR_A])[0]

    assert row["balance_btc"] == 0.001
    assert row["tx_count"] == 5
    assert row["first_seen"] == 1000
    assert row["last_seen"] == 2000
    assert row["dormancy_days"] == 10.0
    assert row["sanctions_hit"] is False
    assert row["wallet_id"] == "wallet123"


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_triage_clusters_addresses_sharing_a_tx(mock_run, mock_fetch):
    mock_run.side_effect = lambda addr: _staged(addr)
    shared_tx = {
        "txid": "t1",
        "vin": [
            {"prevout": {"scriptpubkey_address": ADDR_A}},
            {"prevout": {"scriptpubkey_address": ADDR_B}},
        ],
        "vout": [],
    }
    mock_fetch.return_value = [shared_tx]

    rows = triage_addresses([ADDR_A, ADDR_B])

    cluster_ids = {r["address"]: r["cluster_id"] for r in rows}
    assert cluster_ids[ADDR_A] == cluster_ids[ADDR_B]
    assert cluster_ids[ADDR_A] != ""


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_triage_fetch_error_does_not_abort_batch(mock_run, mock_fetch):
    mock_run.side_effect = lambda addr: _staged(addr)
    mock_fetch.side_effect = ConnectionError("timeout")

    rows = triage_addresses([ADDR_A])
    assert rows[0]["address"] == ADDR_A
    assert rows[0]["valid"] is True


# --- risk flags ---


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_risk_flags_sanctioned(mock_run, mock_fetch):
    mock_run.return_value = _staged(ADDR_A, ofac_sdn={"checked": True, "sanctioned": True})
    mock_fetch.return_value = []
    row = triage_addresses([ADDR_A])[0]
    assert "sanctioned" in row["risk_flags"]


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_risk_flags_sanctions_unavailable(mock_run, mock_fetch):
    mock_run.return_value = _staged(ADDR_A, ofac_sdn={"checked": False, "error": "down"})
    mock_fetch.return_value = []
    row = triage_addresses([ADDR_A])[0]
    assert "sanctions_unavailable" in row["risk_flags"]


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_risk_flags_dormant(mock_run, mock_fetch):
    mock_run.return_value = _staged(ADDR_A, dormancy_days=400.0)
    mock_fetch.return_value = []
    row = triage_addresses([ADDR_A])[0]
    assert "dormant" in row["risk_flags"]


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_risk_flags_high_balance(mock_run, mock_fetch):
    mock_run.return_value = _staged(ADDR_A, blockstream={"balance_btc": 2.5, "balance_sats": 250000000, "tx_count": 1})
    mock_fetch.return_value = []
    row = triage_addresses([ADDR_A])[0]
    assert "high_balance" in row["risk_flags"]


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_risk_flags_balance_fetch_error(mock_run, mock_fetch):
    mock_run.return_value = _staged(ADDR_A, blockstream={"error": "http 503"})
    mock_fetch.return_value = []
    row = triage_addresses([ADDR_A])[0]
    assert "balance_fetch_error" in row["risk_flags"]
    assert "high_balance" not in row["risk_flags"]


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_risk_flags_clean_address_has_no_flags(mock_run, mock_fetch):
    mock_run.return_value = _staged(ADDR_A)
    mock_fetch.return_value = []
    row = triage_addresses([ADDR_A])[0]
    assert row["risk_flags"] == ""


# --- write_triage_csv / run_bulk_triage ---


def test_write_triage_csv_roundtrips(tmp_path):
    rows = [dict.fromkeys(TRIAGE_FIELDNAMES, ""), dict.fromkeys(TRIAGE_FIELDNAMES, "")]
    rows[0]["address"] = ADDR_A
    rows[1]["address"] = ADDR_B

    out_path = str(tmp_path / "out.csv")
    write_triage_csv(rows, out_path)

    with open(out_path, newline="") as f:
        read_back = list(csv.DictReader(f))
    assert [r["address"] for r in read_back] == [ADDR_A, ADDR_B]


@patch("bulk.blockstream.fetch_recent_txs")
@patch("bulk.run_all_staged")
def test_run_bulk_triage_end_to_end(mock_run, mock_fetch, tmp_path):
    mock_run.side_effect = lambda addr: _staged(addr)
    mock_fetch.return_value = []

    in_path = tmp_path / "in.csv"
    in_path.write_text(f"{ADDR_A}\n{ADDR_B}\n")
    out_path = str(tmp_path / "out.csv")

    result_path = run_bulk_triage(str(in_path), out_path)

    assert result_path == out_path
    with open(out_path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["address"] == ADDR_A

from report import generate_address_report, generate_cluster_report

ADDRESS_RESULT = {
    "target": "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a",
    "chain": "bitcoin",
    "target_type": "btc_address_p2pkh",
    "valid": True,
    "blockstream": {
        "balance_btc": 0.0011828,
        "balance_sats": 118280,
        "unconfirmed_balance_sats": 0,
        "tx_count": 152,
        "utxo_count": 3,
    },
    "price": {"usd": 61213},
    "walletexplorer": {"found": True, "wallet_id": "0bee64a8b1819ee9"},
    "ofac_sdn": {"checked": True, "sanctioned": False},
    "first_seen": 1309574535,
    "last_seen": 1568885210,
    "dormancy_days": 2478.3,
}

CLUSTER_ROWS = [
    {
        "address": "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a",
        "balance_btc": 0.0011828,
        "tx_count": 152,
        "dormancy_days": 2478.3,
        "sanctions_hit": False,
        "risk_flags": "dormant",
    },
    {
        "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "balance_btc": "",
        "tx_count": "",
        "dormancy_days": "",
        "sanctions_hit": False,
        "risk_flags": "balance_fetch_error",
    },
]


def _is_valid_pdf(path) -> bool:
    with open(path, "rb") as f:
        return f.read(5) == b"%PDF-"


def test_generate_address_report_creates_valid_pdf(tmp_path):
    out_path = str(tmp_path / "report.pdf")
    result_path = generate_address_report(ADDRESS_RESULT["target"], ADDRESS_RESULT, out_path=out_path)

    assert str(result_path) == out_path
    assert _is_valid_pdf(result_path)


def test_generate_address_report_default_path_uses_target_and_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr("report.Path.home", lambda: tmp_path)
    result_path = generate_address_report(ADDRESS_RESULT["target"], ADDRESS_RESULT)

    assert result_path.exists()
    assert "chainops-" in result_path.name
    assert result_path.suffix == ".pdf"


def test_generate_address_report_handles_invalid_target(tmp_path):
    out_path = str(tmp_path / "invalid.pdf")
    invalid_result = {"target": "garbage!!", "chain": "unknown", "target_type": "unknown", "valid": False, "error": "unrecognized target format"}

    result_path = generate_address_report("garbage!!", invalid_result, out_path=out_path)
    assert _is_valid_pdf(result_path)


def test_generate_address_report_handles_provider_errors(tmp_path):
    out_path = str(tmp_path / "erroneous.pdf")
    result = dict(ADDRESS_RESULT)
    result["blockstream"] = {"error": "http 400: Too many history entries"}

    result_path = generate_address_report(result["target"], result, out_path=out_path)
    assert _is_valid_pdf(result_path)


def test_generate_cluster_report_creates_valid_pdf(tmp_path):
    out_path = str(tmp_path / "cluster.pdf")
    result_path = generate_cluster_report("cluster123", CLUSTER_ROWS, out_path=out_path)

    assert str(result_path) == out_path
    assert _is_valid_pdf(result_path)


def test_generate_cluster_report_handles_empty_rows(tmp_path):
    out_path = str(tmp_path / "empty_cluster.pdf")
    result_path = generate_cluster_report("empty_cluster", [], out_path=out_path)
    assert _is_valid_pdf(result_path)


def test_generate_cluster_report_flags_sanctioned_members(tmp_path):
    out_path = str(tmp_path / "sanctioned_cluster.pdf")
    rows = [dict(CLUSTER_ROWS[0], sanctions_hit=True, risk_flags="sanctioned")]

    result_path = generate_cluster_report("sanctioned_cluster", rows, out_path=out_path)
    assert _is_valid_pdf(result_path)


def test_generate_cluster_report_default_path_uses_cluster_id(tmp_path, monkeypatch):
    monkeypatch.setattr("report.Path.home", lambda: tmp_path)
    result_path = generate_cluster_report("abc123", CLUSTER_ROWS)

    assert result_path.exists()
    assert "cluster-abc123" in result_path.name

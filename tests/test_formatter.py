from formatter import format_cli_report

FULL_RESULT = {
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


def test_invalid_target_short_circuits():
    report = format_cli_report({"target": "garbage!!", "chain": "unknown", "target_type": "unknown", "valid": False, "error": "unrecognized target format"})
    assert "=== TARGET ===" in report
    assert "Error: unrecognized target format" in report
    assert "BALANCE" not in report


def test_unsupported_chain_short_circuits():
    result = {"target": "vitalik.eth", "chain": "ethereum", "target_type": "eth_address", "valid": True, "error": "only BTC supported"}
    report = format_cli_report(result)
    assert "Error: only BTC supported" in report
    assert "BALANCE" not in report


def test_full_report_includes_all_sections():
    report = format_cli_report(FULL_RESULT)
    assert "=== TARGET ===" in report
    assert "=== BALANCE / UTXO ===" in report
    assert "Balance: 0.00118280 BTC (118280 sats)" in report
    assert "=== ACTIVITY ===" in report
    assert "First seen: 2011-07-02" in report
    assert "Last seen: 2019-09-19" in report
    assert "Dormancy: 2478.3 days" in report
    assert "=== PRICE ===" in report
    assert "Current price: $61,213" in report
    assert "Balance value: $" in report
    assert "=== WALLET CLUSTERING ===" in report
    assert "Wallet ID: 0bee64a8b1819ee9" in report
    assert "=== SANCTIONS ===" in report
    assert "No match" in report


def test_sanctioned_match_is_flagged():
    result = dict(FULL_RESULT)
    result["ofac_sdn"] = {"checked": True, "sanctioned": True}
    report = format_cli_report(result)
    assert "SANCTIONED MATCH" in report


def test_ofac_unavailable_shown_as_error_not_false_negative():
    result = dict(FULL_RESULT)
    result["ofac_sdn"] = {"checked": False, "error": "OFAC SDN list unavailable: network unreachable"}
    report = format_cli_report(result)
    assert "Error: OFAC SDN list unavailable" in report
    assert "No match" not in report.split("=== SANCTIONS ===")[1]


def test_walletexplorer_label_shown_when_present():
    result = dict(FULL_RESULT)
    result["walletexplorer"] = {"found": True, "wallet_id": "abc123", "label": "MtGox.com"}
    report = format_cli_report(result)
    assert "Label: MtGox.com" in report


def test_walletexplorer_no_match():
    result = dict(FULL_RESULT)
    result["walletexplorer"] = {"found": False}
    report = format_cli_report(result)
    assert "No cluster match" in report


def test_blockstream_error_shown_in_balance_section():
    result = dict(FULL_RESULT)
    result["blockstream"] = {"error": "http 503: down"}
    report = format_cli_report(result)
    assert "http 503: down" in report


def test_tx_history_error_shown_in_activity_section():
    result = dict(FULL_RESULT)
    del result["first_seen"]
    del result["last_seen"]
    del result["dormancy_days"]
    result["tx_history_error"] = "could not fetch full tx history: timeout"
    report = format_cli_report(result)
    assert "could not fetch full tx history: timeout" in report


TRON_RESULT = {
    "target": "TXFBqBbqJommqZf7BV8NNYzePh97UmJodJ",
    "chain": "tron",
    "target_type": "tron_address",
    "valid": True,
    "tron": {
        "balance_trx": 5.0,
        "activated": True,
        "usdt_transfer_count": 2,
    },
    "price": {"usd": 0.12},
    "ofac_sdn": {"checked": True, "sanctioned": False},
    "first_seen": 1700000000,
    "last_seen": 1700005000,
    "dormancy_days": 300.5,
}


def test_tron_report_includes_balance_and_activity_not_wallet_clustering():
    report = format_cli_report(TRON_RESULT)
    assert "=== BALANCE ===" in report
    assert "Balance: 5.000000 TRX" in report
    assert "USDT (TRC20) transfers seen: 2" in report
    assert "=== ACTIVITY ===" in report
    assert "First seen: 2023-11-14" in report
    assert "Dormancy: 300.5 days" in report
    assert "Balance value: $0.60" in report
    assert "=== WALLET CLUSTERING ===" not in report
    assert "=== SANCTIONS ===" in report
    assert "No match" in report


def test_tron_report_flags_unactivated_address():
    result = dict(TRON_RESULT)
    result["tron"] = {"balance_trx": 0.0, "activated": False, "usdt_transfer_count": 0}
    report = format_cli_report(result)
    assert "(unactivated address)" in report


def test_tron_report_shows_balance_error():
    result = dict(TRON_RESULT)
    result["tron"] = {"error": "http 503: down"}
    report = format_cli_report(result)
    assert "http 503: down" in report

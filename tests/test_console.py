from unittest.mock import patch

from console import ConsoleSession, run_console

SEED = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"


def _walk(nodes, edges, truncated=False, fetch_errors=None):
    return {
        "seed": SEED,
        "valid": True,
        "nodes": nodes,
        "edges": edges,
        "truncated": truncated,
        "fetch_errors": fetch_errors or {},
    }


# --- ConsoleSession.handle_query ---


@patch("console.run_all_staged")
def test_handle_query_sets_seed_and_formats_report(mock_run):
    mock_run.return_value = {"target": SEED, "chain": "bitcoin", "target_type": "btc_address_p2pkh", "valid": True}
    session = ConsoleSession()

    report = session.handle_query(SEED)

    assert session.seed == SEED
    assert "=== TARGET ===" in report


# --- ConsoleSession.handle_expand ---


@patch("console.expand_neighbors")
def test_handle_expand_requires_seed_when_no_address_given(mock_expand):
    session = ConsoleSession()
    result = session.handle_expand(None)
    assert "no seed set" in result
    mock_expand.assert_not_called()


@patch("console.expand_neighbors")
def test_handle_expand_uses_current_seed_when_no_address_given(mock_expand):
    mock_expand.return_value = _walk({SEED: {"depth": 0}, "addrB": {"depth": 1}}, [{"txid": "t1", "from": SEED, "to": "addrB"}])
    session = ConsoleSession()
    session.seed = SEED

    result = session.handle_expand(None)

    mock_expand.assert_called_once_with(SEED, depth=1)
    assert "new node" in result


@patch("console.expand_neighbors")
def test_handle_expand_merges_into_session_graph(mock_expand):
    mock_expand.return_value = _walk(
        {SEED: {"depth": 0}, "addrB": {"depth": 1}, "addrC": {"depth": 1}},
        [{"txid": "t1", "from": SEED, "to": "addrB"}, {"txid": "t1", "from": SEED, "to": "addrC"}],
    )
    session = ConsoleSession()

    result = session.handle_expand(SEED)

    assert len(session.nodes) == 3
    assert len(session.edges) == 2
    assert "+3 new node(s)" in result
    assert "+2 new edge(s)" in result


@patch("console.expand_neighbors")
def test_handle_expand_reports_truncation_and_fetch_errors(mock_expand):
    mock_expand.return_value = _walk(
        {SEED: {"depth": 0}}, [], truncated=True, fetch_errors={"addrX": "timeout"}
    )
    session = ConsoleSession()

    result = session.handle_expand(SEED)

    assert "truncated" in result
    assert "1 address(es) failed" in result


@patch("console.expand_neighbors")
def test_handle_expand_surfaces_invalid_target_error(mock_expand):
    mock_expand.return_value = {"seed": "garbage", "valid": False, "error": "unrecognized target format"}
    session = ConsoleSession()

    result = session.handle_expand("garbage")

    assert "error: unrecognized target format" in result


@patch("console.expand_neighbors")
def test_handle_expand_does_not_duplicate_edges_across_calls(mock_expand):
    walk = _walk({SEED: {"depth": 0}, "addrB": {"depth": 1}}, [{"txid": "t1", "from": SEED, "to": "addrB"}])
    mock_expand.return_value = walk
    session = ConsoleSession()

    session.handle_expand(SEED)
    result = session.handle_expand(SEED)

    assert len(session.edges) == 1
    assert "+0 new node(s), +0 new edge(s)" in result


# --- ConsoleSession.handle_depth ---


def test_handle_depth_sets_valid_value():
    session = ConsoleSession()
    result = session.handle_depth("3")
    assert session.depth == 3
    assert "depth set to 3" in result


def test_handle_depth_rejects_non_integer():
    session = ConsoleSession()
    result = session.handle_depth("abc")
    assert session.depth == 1
    assert "must be an integer" in result


def test_handle_depth_rejects_zero_or_negative():
    session = ConsoleSession()
    result = session.handle_depth("0")
    assert session.depth == 1
    assert "must be >= 1" in result


# --- ConsoleSession.handle_graph / handle_status / handle_reset ---


def test_handle_graph_empty_session():
    session = ConsoleSession()
    assert "empty" in session.handle_graph()


@patch("console.expand_neighbors")
def test_handle_graph_lists_nodes_by_depth(mock_expand):
    mock_expand.return_value = _walk({SEED: {"depth": 0}, "addrB": {"depth": 1}}, [])
    session = ConsoleSession()
    session.seed = SEED
    session.handle_expand(SEED)

    report = session.handle_graph()
    assert "2 node(s)" in report
    assert "(seed)" in report


@patch("console.expand_neighbors")
def test_handle_graph_flags_sanctioned_and_contract_nodes(mock_expand):
    mock_expand.return_value = _walk(
        {SEED: {"depth": 0}, "addrB": {"depth": 1, "is_contract": True}, "addrC": {"depth": 1, "sanctioned": True}}, []
    )
    session = ConsoleSession()
    session.handle_expand(SEED)

    report = session.handle_graph()
    assert "addrB [contract]" in report
    assert "addrC [!] SANCTIONED" in report


def test_handle_status_reports_seed_depth_and_graph_size():
    session = ConsoleSession()
    session.seed = SEED
    session.depth = 2
    status = session.handle_status()
    assert SEED in status
    assert "depth: 2" in status
    assert "0 node(s), 0 edge(s)" in status


@patch("console.expand_neighbors")
def test_handle_reset_clears_graph_but_not_seed(mock_expand):
    mock_expand.return_value = _walk({SEED: {"depth": 0}, "addrB": {"depth": 1}}, [{"txid": "t1", "from": SEED, "to": "addrB"}])
    session = ConsoleSession()
    session.seed = SEED
    session.handle_expand(SEED)

    session.handle_reset()

    assert session.nodes == {}
    assert session.edges == []
    assert session.truncated is False
    assert session.seed == SEED


# --- ConsoleSession.handle_draw ---


def test_handle_draw_requires_a_graph():
    session = ConsoleSession()
    result = session.handle_draw(None)
    assert "empty" in result


@patch("console.expand_neighbors")
@patch("draw.save_drawio_file")
def test_handle_draw_saves_and_reports_path(mock_save, mock_expand):
    mock_expand.return_value = _walk({SEED: {"depth": 0}, "addrB": {"depth": 1}}, [{"txid": "t1", "from": SEED, "to": "addrB"}])
    mock_save.return_value = "/tmp/chainops-map-20260702.drawio"
    session = ConsoleSession()
    session.seed = SEED
    session.handle_expand(SEED)

    result = session.handle_draw(None)

    mock_save.assert_called_once_with(session.nodes, session.edges, seed=SEED, out_path=None)
    assert "/tmp/chainops-map-20260702.drawio" in result
    assert "2 node(s), 1 edge(s)" in result


@patch("console.expand_neighbors")
@patch("draw.save_drawio_file")
def test_handle_draw_passes_through_custom_path(mock_save, mock_expand):
    mock_expand.return_value = _walk({SEED: {"depth": 0}}, [])
    mock_save.return_value = "/custom/out.drawio"
    session = ConsoleSession()
    session.handle_expand(SEED)

    session.handle_draw("/custom/out.drawio")

    mock_save.assert_called_once_with(session.nodes, session.edges, seed=None, out_path="/custom/out.drawio")


# --- run_console() I/O loop ---


@patch("console.run_all_staged")
def test_run_console_exits_on_exit_command(mock_run, capsys):
    with patch("builtins.input", side_effect=["exit"]):
        rc = run_console()
    assert rc == 0
    mock_run.assert_not_called()


def test_run_console_exits_on_eof():
    with patch("builtins.input", side_effect=EOFError):
        rc = run_console()
    assert rc == 0


@patch("console.run_all_staged")
def test_run_console_dispatches_bare_target_to_query(mock_run, capsys):
    mock_run.return_value = {"target": SEED, "chain": "bitcoin", "target_type": "btc_address_p2pkh", "valid": True}
    with patch("builtins.input", side_effect=[SEED, "exit"]):
        run_console()
    out = capsys.readouterr().out
    assert "=== TARGET ===" in out


def test_run_console_help_and_depth_commands(capsys):
    with patch("builtins.input", side_effect=["help", "depth 3", "depth", "exit"]):
        run_console()
    out = capsys.readouterr().out
    assert "Query" in out
    assert "depth set to 3" in out
    assert "depth is 3" in out


# --- ConsoleSession.handle_bulk_inline / handle_bulk_file ---


ADDR_B = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"


def _triage_row(address, **overrides):
    row = {
        "address": address,
        "valid": True,
        "error": "",
        "balance_btc": 0.001,
        "balance_sats": 100000,
        "tx_count": 5,
        "first_seen": 1000,
        "last_seen": 2000,
        "dormancy_days": 10.0,
        "cluster_id": "",
        "sanctions_hit": False,
        "wallet_id": "",
        "risk_flags": "",
    }
    row.update(overrides)
    return row


def test_handle_bulk_inline_rejects_empty_list():
    session = ConsoleSession()
    result = session.handle_bulk_inline([])
    assert "no addresses given" in result


@patch("bulk.write_triage_csv")
@patch("bulk.triage_addresses")
def test_handle_bulk_inline_triages_and_saves_csv(mock_triage, mock_write):
    rows = [_triage_row(SEED), _triage_row(ADDR_B)]
    mock_triage.return_value = rows
    mock_write.return_value = "/tmp/chainops-bulk-20260702.csv"
    session = ConsoleSession()

    result = session.handle_bulk_inline([SEED, ADDR_B])

    mock_triage.assert_called_once_with([SEED, ADDR_B])
    assert session.last_triage_rows == rows
    assert "triaged 2 address(es)" in result
    assert "saved to" in result


@patch("bulk.write_triage_csv")
@patch("bulk.triage_addresses")
def test_handle_bulk_inline_flags_sanctioned_and_errored_rows(mock_triage, mock_write):
    mock_triage.return_value = [
        _triage_row(SEED, sanctions_hit=True, risk_flags="sanctioned"),
        _triage_row(ADDR_B, error="http 500", valid=False),
    ]
    mock_write.return_value = "/tmp/out.csv"
    session = ConsoleSession()

    result = session.handle_bulk_inline([SEED, ADDR_B])

    assert "1 address(es) matched the OFAC SDN list" in result
    assert "1 address(es) failed to fetch" in result


@patch("console.ConsoleSession.handle_bulk_inline")
@patch("bulk.read_addresses_csv")
def test_handle_bulk_file_reads_csv_then_triages(mock_read, mock_inline):
    mock_read.return_value = [SEED, ADDR_B]
    mock_inline.return_value = "triaged 2 address(es), saved to /tmp/out.csv"
    session = ConsoleSession()

    result = session.handle_bulk_file("addresses.csv")

    mock_read.assert_called_once_with("addresses.csv")
    mock_inline.assert_called_once_with([SEED, ADDR_B])
    assert "triaged 2 address(es)" in result


@patch("bulk.read_addresses_csv")
def test_handle_bulk_file_reports_empty_csv(mock_read):
    mock_read.return_value = []
    session = ConsoleSession()

    result = session.handle_bulk_file("empty.csv")

    assert "no addresses found" in result


@patch("bulk.read_addresses_csv")
def test_handle_bulk_file_reports_read_error(mock_read):
    mock_read.side_effect = OSError("not found")
    session = ConsoleSession()

    result = session.handle_bulk_file("missing.csv")

    assert "error: could not read missing.csv" in result


# --- ConsoleSession.handle_report / handle_report_cluster ---


def test_handle_report_requires_a_query_first():
    session = ConsoleSession()
    result = session.handle_report(None)
    assert "no query result yet" in result


@patch("report.generate_address_report")
def test_handle_report_generates_pdf_from_last_result(mock_generate):
    mock_generate.return_value = "/tmp/chainops-report.pdf"
    session = ConsoleSession()
    session.last_result = {"target": SEED, "valid": True}

    result = session.handle_report(None)

    mock_generate.assert_called_once_with(SEED, session.last_result, None)
    assert "/tmp/chainops-report.pdf" in result


@patch("report.generate_address_report")
def test_handle_report_surfaces_missing_fpdf(mock_generate):
    mock_generate.side_effect = RuntimeError("PDF generation requires fpdf2. Install with: pip install fpdf2")
    session = ConsoleSession()
    session.last_result = {"target": SEED, "valid": True}

    result = session.handle_report(None)

    assert "error:" in result
    assert "fpdf2" in result


def test_handle_report_cluster_requires_a_bulk_run_first():
    session = ConsoleSession()
    result = session.handle_report_cluster("cluster1", None)
    assert "run 'bulk' first" in result


def test_handle_report_cluster_requires_matching_rows():
    session = ConsoleSession()
    session.last_triage_rows = [_triage_row(SEED, cluster_id="other")]

    result = session.handle_report_cluster("cluster1", None)

    assert "no rows found" in result


@patch("report.generate_cluster_report")
def test_handle_report_cluster_generates_pdf_from_matching_rows(mock_generate):
    mock_generate.return_value = "/tmp/chainops-cluster.pdf"
    session = ConsoleSession()
    rows = [_triage_row(SEED, cluster_id="cluster1"), _triage_row(ADDR_B, cluster_id="other")]
    session.last_triage_rows = rows

    result = session.handle_report_cluster("cluster1", None)

    mock_generate.assert_called_once_with("cluster1", [rows[0]], None)
    assert "1 member(s)" in result
    assert "/tmp/chainops-cluster.pdf" in result


# --- run_console() bulk/report command dispatch ---


@patch("console.ConsoleSession.handle_bulk_inline")
def test_run_console_bulk_inline_command(mock_handle, capsys):
    mock_handle.return_value = "triaged 2 address(es), saved to /tmp/out.csv"
    with patch("builtins.input", side_effect=[f"bulk {SEED}, {ADDR_B}", "exit"]):
        run_console()
    mock_handle.assert_called_once_with([SEED, ADDR_B])
    assert "triaged 2 address(es)" in capsys.readouterr().out


@patch("console.ConsoleSession.handle_bulk_file")
def test_run_console_bulk_file_command(mock_handle, tmp_path, capsys):
    csv_path = tmp_path / "addrs.csv"
    csv_path.write_text(SEED + "\n")
    mock_handle.return_value = "triaged 1 address(es), saved to /tmp/out.csv"
    with patch("builtins.input", side_effect=[f"bulk {csv_path}", "exit"]):
        run_console()
    mock_handle.assert_called_once_with(str(csv_path))
    assert "triaged 1 address(es)" in capsys.readouterr().out


@patch("console.ConsoleSession.handle_bulk_inline")
def test_run_console_bulk_paste_mode(mock_handle, capsys):
    mock_handle.return_value = "triaged 2 address(es), saved to /tmp/out.csv"
    with patch("builtins.input", side_effect=["bulk", SEED, ADDR_B, "", "exit"]):
        run_console()
    mock_handle.assert_called_once_with([SEED, ADDR_B])
    assert "triaged 2 address(es)" in capsys.readouterr().out


@patch("console.ConsoleSession.handle_report")
def test_run_console_report_command(mock_handle, capsys):
    mock_handle.return_value = "saved report to /tmp/report.pdf"
    with patch("builtins.input", side_effect=["report", "exit"]):
        run_console()
    mock_handle.assert_called_once_with(None)
    assert "saved report to /tmp/report.pdf" in capsys.readouterr().out


@patch("console.ConsoleSession.handle_report_cluster")
def test_run_console_report_cluster_command(mock_handle, capsys):
    mock_handle.return_value = "saved cluster report (2 member(s)) to /tmp/cluster.pdf"
    with patch("builtins.input", side_effect=["report cluster cluster1", "exit"]):
        run_console()
    mock_handle.assert_called_once_with("cluster1", None)
    assert "saved cluster report" in capsys.readouterr().out


def test_run_console_report_cluster_requires_cluster_id(capsys):
    with patch("builtins.input", side_effect=["report cluster", "exit"]):
        run_console()
    assert "usage: report cluster" in capsys.readouterr().out


# --- render_providers_status / 'providers' and 'set-key' console commands ---


from console import render_providers_status  # noqa: E402


def test_render_providers_status_shows_configured_and_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAINOPS_KEYS_DIR", str(tmp_path))
    monkeypatch.setenv("ETHERSCAN_API_KEY", "abcd1234")
    monkeypatch.delenv("TRONGRID_API_KEY", raising=False)
    import importlib

    import keystore
    from enrichment.providers import _registry

    importlib.reload(keystore)
    importlib.reload(_registry)

    text = render_providers_status(use_color=False)

    assert "Etherscan" in text
    assert "Configured" in text
    assert "TronGrid" in text
    assert "Missing" in text


@patch("console.render_providers_status")
def test_run_console_providers_command(mock_render, capsys):
    mock_render.return_value = "fake provider status"
    with patch("builtins.input", side_effect=["providers", "exit"]):
        run_console()
    mock_render.assert_called_once_with(False)
    assert "fake provider status" in capsys.readouterr().out


@patch("keystore.run_setup_wizard")
def test_run_console_set_key_no_args_runs_wizard(mock_wizard, capsys):
    with patch("builtins.input", side_effect=["set-key", "exit"]):
        run_console()
    mock_wizard.assert_called_once()


def test_run_console_set_key_rejects_unknown_provider(capsys):
    with patch("builtins.input", side_effect=["set-key bogus somekey", "exit"]):
        run_console()
    out = capsys.readouterr().out
    assert "unknown provider 'bogus'" in out


@patch("keystore.set_key")
def test_run_console_set_key_direct_sets_value(mock_set, capsys):
    with patch("builtins.input", side_effect=["set-key evm mykey123", "exit"]):
        run_console()
    mock_set.assert_called_once_with("ETHERSCAN_API_KEY", "mykey123")
    assert "Etherscan" in capsys.readouterr().out


@patch("keystore.set_key")
def test_run_console_set_key_single_provider_prompts_for_value(mock_set, capsys):
    with patch("builtins.input", side_effect=["set-key evm", "prompted-key", "exit"]):
        run_console()
    mock_set.assert_called_once_with("ETHERSCAN_API_KEY", "prompted-key")


@patch("keystore.set_key")
def test_run_console_set_key_single_provider_blank_input_is_no_change(mock_set, capsys):
    with patch("builtins.input", side_effect=["set-key evm", "", "exit"]):
        run_console()
    mock_set.assert_not_called()
    assert "no change" in capsys.readouterr().out

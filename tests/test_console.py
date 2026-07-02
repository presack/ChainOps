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

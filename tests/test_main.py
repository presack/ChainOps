import json
import sys
from unittest.mock import patch

import pytest

from main import main, parse_args, run_cli


@patch("main.run_all_staged")
def test_run_cli_prints_formatted_report_by_default(mock_run, capsys):
    mock_run.return_value = {"target": "addr", "chain": "bitcoin", "target_type": "btc_address_p2pkh", "valid": True}
    run_cli("addr", as_json=False)
    out = capsys.readouterr().out
    assert "=== TARGET ===" in out


@patch("main.run_all_staged")
def test_run_cli_prints_json_when_flagged(mock_run, capsys):
    mock_run.return_value = {"target": "addr", "chain": "bitcoin", "valid": True}
    run_cli("addr", as_json=True)
    out = capsys.readouterr().out
    assert json.loads(out) == {"target": "addr", "chain": "bitcoin", "valid": True}


@patch("main.run_all_staged")
def test_run_cli_returns_zero_on_success(mock_run):
    mock_run.return_value = {"valid": True}
    assert run_cli("addr", as_json=True) == 0


@patch("main.run_all_staged")
def test_run_cli_returns_nonzero_on_invalid_target(mock_run):
    mock_run.return_value = {"valid": False, "error": "unrecognized target format"}
    assert run_cli("garbage!!", as_json=True) == 1


@patch("main.run_all_staged")
def test_run_cli_returns_nonzero_on_valid_but_errored_target(mock_run):
    mock_run.return_value = {"valid": True, "error": "only BTC supported"}
    assert run_cli("vitalik.eth", as_json=True) == 1


def test_main_requires_target_unless_console(capsys):
    with patch.object(sys, "argv", ["main.py"]):
        rc = main()
    assert rc == 1
    assert "target is required" in capsys.readouterr().out


@patch("console.run_console")
def test_main_dispatches_to_console(mock_console):
    mock_console.return_value = 0
    with patch.object(sys, "argv", ["main.py", "--console"]):
        rc = main()
    assert rc == 0
    mock_console.assert_called_once()


@patch("main.run_all_staged")
def test_main_dispatches_target_to_run_cli(mock_run, capsys):
    mock_run.return_value = {"valid": True, "target": "addr"}
    with patch.object(sys, "argv", ["main.py", "addr", "--json"]):
        rc = main()
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"valid": True, "target": "addr"}


def test_version_flag_prints_version_and_exits(capsys):
    with patch.object(sys, "argv", ["main.py", "--version"]):
        with pytest.raises(SystemExit) as exc_info:
            parse_args()
    assert exc_info.value.code == 0
    assert "ChainOps" in capsys.readouterr().out


def test_help_output_is_grouped(capsys):
    with patch.object(sys, "argv", ["main.py", "--help"]):
        with pytest.raises(SystemExit):
            parse_args()
    out = capsys.readouterr().out
    assert "execution mode" in out
    assert "query options" in out
    assert "key management" in out
    assert "web server" in out

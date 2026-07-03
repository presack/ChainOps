import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from web_ui import build_app, render_result_html

SEED = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"


def _client() -> TestClient:
    return TestClient(build_app())


# --- routes ---


def test_home_page_renders_query_form():
    resp = _client().get("/")
    assert resp.status_code == 200
    assert "ChainOps" in resp.text
    assert 'id="query-form"' in resp.text
    assert 'id="target"' in resp.text


def test_query_start_rejects_empty_target():
    resp = _client().post("/query/start", data={"target": "   "})
    assert resp.status_code == 400
    assert "target is required" in resp.json()["error"]


@patch("web_ui.run_all_staged")
def test_query_start_returns_job_id_then_status_resolves(mock_run):
    mock_run.return_value = {
        "target": SEED,
        "chain": "bitcoin",
        "target_type": "btc_address_p2pkh",
        "valid": True,
        "blockstream": {"balance_btc": 0.001, "balance_sats": 100000, "tx_count": 5},
        "price": {"usd": 60000},
        "walletexplorer": {"found": False},
        "ofac_sdn": {"checked": True, "sanctioned": False},
    }
    client = _client()

    start_resp = client.post("/query/start", data={"target": SEED})
    assert start_resp.status_code == 200
    job_id = start_resp.json()["job_id"]
    assert job_id

    status = _poll_until_done(client, job_id)
    assert status["error"] is None
    assert "=== TARGET ===" not in status["html"]  # rendered as HTML, not raw text
    assert SEED in status["html"]
    assert "Balance" in status["html"]
    mock_run.assert_called_once_with(SEED)


@patch("web_ui.run_all_staged", side_effect=RuntimeError("boom"))
def test_query_start_surfaces_worker_exception_via_status(mock_run):
    client = _client()
    start_resp = client.post("/query/start", data={"target": SEED})
    job_id = start_resp.json()["job_id"]

    status = _poll_until_done(client, job_id)
    assert status["error"] is not None
    assert "boom" in status["error"]


def test_query_status_unknown_job_id_returns_404():
    resp = _client().get("/query/status/does-not-exist")
    assert resp.status_code == 404
    assert "unknown job_id" in resp.json()["error"]


def _poll_until_done(client: TestClient, job_id: str, timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/query/status/{job_id}").json()
        if status["done"]:
            return status
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not complete within {timeout}s")


# --- render_result_html ---


def test_render_result_html_wraps_sections_in_cards():
    result = {
        "target": SEED,
        "chain": "bitcoin",
        "target_type": "btc_address_p2pkh",
        "valid": True,
        "blockstream": {"balance_btc": 0.001, "balance_sats": 100000, "tx_count": 5},
        "price": {"usd": 60000},
        "walletexplorer": {"found": False},
        "ofac_sdn": {"checked": True, "sanctioned": False},
    }
    html = render_result_html(result)
    assert "=== TARGET ===" not in html
    assert "TARGET" in html
    assert "bg-slate-800/70" in html
    assert SEED in html


def test_render_result_html_flags_sanctioned_match_in_red():
    result = {
        "target": SEED,
        "chain": "bitcoin",
        "target_type": "btc_address_p2pkh",
        "valid": True,
        "blockstream": {"balance_btc": 0.001, "balance_sats": 100000, "tx_count": 5},
        "price": {"usd": 60000},
        "walletexplorer": {"found": False},
        "ofac_sdn": {"checked": True, "sanctioned": True},
    }
    html = render_result_html(result)
    assert "text-red-400" in html
    assert "SANCTIONED MATCH" in html


def test_render_result_html_escapes_html_in_values():
    result = {
        "target": "<script>alert(1)</script>",
        "chain": "unknown",
        "target_type": "unknown",
        "valid": False,
        "error": "unrecognized target format",
    }
    html = render_result_html(result)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html

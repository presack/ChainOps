from unittest.mock import Mock

from core_ops import Chain
from enrichment.providers._shared import error_result, require_chain, short_http_error


def test_require_chain_accepts_matching_chain():
    result = require_chain("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", Chain.BITCOIN, "blockstream")
    assert result.valid
    assert result.chain == Chain.BITCOIN


def test_require_chain_rejects_wrong_chain():
    result = require_chain("vitalik.eth", Chain.BITCOIN, "blockstream")
    assert isinstance(result, dict)
    assert result["source"] == "blockstream"
    assert "bitcoin" in result["error"]
    assert "ethereum" in result["error"]


def test_require_chain_rejects_invalid_target():
    result = require_chain("not-a-real-target!!", Chain.BITCOIN, "blockstream")
    assert isinstance(result, dict)
    assert result["source"] == "blockstream"
    assert "unrecognized target" in result["error"]


def test_error_result_omits_target_type_when_not_given():
    result = error_result("blockstream", "boom")
    assert result == {"source": "blockstream", "error": "boom"}


def test_short_http_error_truncates_long_body():
    response = Mock(status_code=500, text="x" * 200)
    message = short_http_error(response)
    assert message.startswith("http 500: ")
    assert len(message) < 160


def test_short_http_error_handles_empty_body():
    response = Mock(status_code=404, text="   ")
    assert short_http_error(response) == "http 404: request failed"


def test_fake_provider_satisfies_contract():
    """A minimal provider using the shared helpers, exercised end to end."""

    def run(target: str, key: str) -> dict:
        classified = require_chain(target, Chain.BITCOIN, "fake")
        if isinstance(classified, dict):
            return classified
        return {"source": "fake", "chain": classified.chain, "balance_sats": 0}

    def summary(payload: dict) -> str:
        if "error" in payload:
            return f"fake error={payload['error']}"
        return f"fake balance_sats={payload['balance_sats']}"

    ok = run("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", "")
    assert summary(ok) == "fake balance_sats=0"

    bad = run("vitalik.eth", "")
    assert summary(bad).startswith("fake error=")

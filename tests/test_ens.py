from unittest.mock import Mock, patch

import requests

from enrichment.providers import _evm_rpc, ens

VITALIK_ETH = "vitalik.eth"
RESOLVED_ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
RESOLVER_ADDRESS = "0x231b0Ee14048e9dCCD1d247744d114a4EB5E8E63"


# --- keccak256 / namehash / checksum -- verified against known reference values ---


def test_keccak256_empty_string_matches_known_vector():
    assert ens.keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"


def test_namehash_empty_name_is_32_zero_bytes():
    result = ens.namehash("")
    assert len(result) == 32
    assert result == b"\x00" * 32


def test_namehash_is_deterministic_and_32_bytes():
    result = ens.namehash(VITALIK_ETH)
    assert len(result) == 32
    assert result == ens.namehash(VITALIK_ETH)


def test_namehash_differs_per_name():
    assert ens.namehash("vitalik.eth") != ens.namehash("nick.eth")


def test_to_checksum_address_matches_known_vector():
    assert ens.to_checksum_address(RESOLVED_ADDRESS.lower()) == RESOLVED_ADDRESS


# --- resolve_ens -- mocked JSON-RPC eth_call responses ---


def _rpc_response(hex_result: str) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": hex_result}


def _padded_address(address: str) -> str:
    return "0x" + address[2:].lower().rjust(64, "0")


def _mock_post(response_for):
    """response_for(to_address) -> hex result string, keyed by the `to`
    field of the eth_call so fallback/retry logic doesn't depend on call
    order."""

    def _post(url, json=None, timeout=None):
        to = json["params"][0]["to"]
        resp = Mock(spec=requests.Response)
        resp.status_code = 200
        resp.raise_for_status = Mock()
        resp.json.return_value = _rpc_response(response_for(to))
        return resp

    return _post


def test_resolve_ens_success():
    def response_for(to):
        if to == ens._ENS_REGISTRY:
            return _padded_address(RESOLVER_ADDRESS)
        return _padded_address(RESOLVED_ADDRESS)

    with patch("enrichment.providers._evm_rpc.requests.post", side_effect=_mock_post(response_for)):
        result = ens.resolve_ens(VITALIK_ETH)

    assert result["error"] is None
    assert result["address"] == RESOLVED_ADDRESS


def test_resolve_ens_unregistered_name_has_no_resolver():
    def response_for(to):
        return ens._ZERO_ADDRESS  # registry returns the zero address: no resolver set

    with patch("enrichment.providers._evm_rpc.requests.post", side_effect=_mock_post(response_for)):
        result = ens.resolve_ens("definitely-not-registered-xyz123.eth")

    assert result["address"] is None
    assert "no resolver" in result["error"]


def test_resolve_ens_registered_but_no_address_set():
    def response_for(to):
        if to == ens._ENS_REGISTRY:
            return _padded_address(RESOLVER_ADDRESS)
        return ens._ZERO_ADDRESS  # resolver exists but addr() is unset

    with patch("enrichment.providers._evm_rpc.requests.post", side_effect=_mock_post(response_for)):
        result = ens.resolve_ens(VITALIK_ETH)

    assert result["address"] is None
    assert "no ETH address set" in result["error"]


def test_resolve_ens_falls_back_to_next_rpc_endpoint_on_failure():
    call_count = {"n": 0}

    def _post(url, json=None, timeout=None):
        call_count["n"] += 1
        if url == _evm_rpc.RPC_ENDPOINTS[0]:
            raise requests.ConnectionError("endpoint down")
        to = json["params"][0]["to"]
        resp = Mock(spec=requests.Response)
        resp.status_code = 200
        resp.raise_for_status = Mock()
        if to == ens._ENS_REGISTRY:
            resp.json.return_value = _rpc_response(_padded_address(RESOLVER_ADDRESS))
        else:
            resp.json.return_value = _rpc_response(_padded_address(RESOLVED_ADDRESS))
        return resp

    with patch("enrichment.providers._evm_rpc.requests.post", side_effect=_post):
        result = ens.resolve_ens(VITALIK_ETH)

    assert result["error"] is None
    assert result["address"] == RESOLVED_ADDRESS
    assert call_count["n"] > 2  # at least one retry happened


def test_resolve_ens_all_endpoints_failing_returns_error():
    with patch("enrichment.providers._evm_rpc.requests.post", side_effect=requests.ConnectionError("down")):
        result = ens.resolve_ens(VITALIK_ETH)

    assert result["address"] is None
    assert "registry lookup failed" in result["error"]

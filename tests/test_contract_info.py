from unittest.mock import Mock, patch

import requests

from enrichment.providers import contract_info

ROUTER = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
EOA = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
DELEGATE = "0x5a7fc11397e9a8ad41bf10bf13f22b0a63f96f6d"


def _mock_response(json_data, status_code=200):
    resp = Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = ""
    return resp


# --- classify_address ---


@patch("enrichment.providers.contract_info.rpc_call")
def test_classify_address_eoa_has_empty_code(rpc):
    rpc.return_value = "0x"

    result = contract_info.classify_address(EOA)

    assert result == {"kind": "eoa", "delegate_address": None, "error": None}


@patch("enrichment.providers.contract_info.rpc_call")
def test_classify_address_contract_has_real_bytecode(rpc):
    rpc.return_value = "0x608060405234801561001057600080fd5b50"

    result = contract_info.classify_address(ROUTER)

    assert result["kind"] == "contract"
    assert result["delegate_address"] is None


@patch("enrichment.providers.contract_info.rpc_call")
def test_classify_address_eip7702_delegation_is_still_an_eoa(rpc):
    # Regression: an EIP-7702-delegated EOA has non-empty bytecode (the
    # 0xef0100 + 20-byte-address designator) but is NOT a smart contract --
    # confirmed live 2026-07-02 against vitalik.eth's own address.
    rpc.return_value = "0xef0100" + DELEGATE[2:]

    result = contract_info.classify_address(EOA)

    assert result["kind"] == "delegated_eoa"
    assert result["delegate_address"] == DELEGATE


@patch("enrichment.providers.contract_info.rpc_call", side_effect=RuntimeError("all RPC endpoints failed"))
def test_classify_address_surfaces_rpc_failure(rpc):
    result = contract_info.classify_address(EOA)

    assert result["kind"] is None
    assert "contract detection failed" in result["error"]


# --- get_verified_contract_name ---


@patch("enrichment.providers.contract_info.requests.get")
def test_get_verified_contract_name_returns_name_for_verified_contract(get: Mock):
    get.return_value = _mock_response({"status": "1", "message": "OK", "result": [{"ContractName": "UniswapV2Router02"}]})

    result = contract_info.get_verified_contract_name(ROUTER, "my-key")

    assert result == "UniswapV2Router02"


@patch("enrichment.providers.contract_info.requests.get")
def test_get_verified_contract_name_returns_none_for_unverified_or_eoa(get: Mock):
    get.return_value = _mock_response({"status": "1", "message": "OK", "result": [{"ContractName": ""}]})

    result = contract_info.get_verified_contract_name(EOA, "my-key")

    assert result is None


def test_get_verified_contract_name_returns_none_without_key():
    result = contract_info.get_verified_contract_name(ROUTER, "")
    assert result is None


@patch("enrichment.providers.contract_info.requests.get", side_effect=requests.ConnectionError("down"))
def test_get_verified_contract_name_returns_none_on_request_failure(get: Mock):
    result = contract_info.get_verified_contract_name(ROUTER, "my-key")
    assert result is None


# --- tag_address ---


@patch("enrichment.providers.contract_info.get_verified_contract_name", return_value="UniswapV2Router02")
@patch("enrichment.providers.contract_info.classify_address", return_value={"kind": "contract", "delegate_address": None, "error": None})
def test_tag_address_combines_classification_and_name(classify, name):
    result = contract_info.tag_address(ROUTER, "my-key")

    assert result["kind"] == "contract"
    assert result["contract_name"] == "UniswapV2Router02"


@patch("enrichment.providers.contract_info.get_verified_contract_name", return_value="AmbireAccount7702")
@patch(
    "enrichment.providers.contract_info.classify_address",
    return_value={"kind": "delegated_eoa", "delegate_address": DELEGATE, "error": None},
)
def test_tag_address_looks_up_delegate_name_for_delegated_eoa(classify, name):
    result = contract_info.tag_address(EOA, "my-key")

    assert result["kind"] == "delegated_eoa"
    assert result["contract_name"] == "AmbireAccount7702"
    name.assert_called_once_with(DELEGATE, "my-key")


@patch("enrichment.providers.contract_info.get_verified_contract_name")
@patch("enrichment.providers.contract_info.classify_address", return_value={"kind": "eoa", "delegate_address": None, "error": None})
def test_tag_address_skips_name_lookup_for_plain_eoa(classify, name):
    result = contract_info.tag_address(EOA, "my-key")

    assert result["contract_name"] is None
    name.assert_not_called()

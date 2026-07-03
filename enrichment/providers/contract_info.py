"""EVM contract detection + known-address labeling.

classify_address() distinguishes true contracts from EOAs via
eth_getCode (free public RPC, no Etherscan key needed), but specifically
handles EIP-7702 (live on Ethereum mainnet since the Pectra upgrade): a
"delegated EOA" has non-empty bytecode (a 23-byte 0xef0100 + 20-byte-
address designator) but is still fundamentally an EOA -- naively treating
any non-empty bytecode as "is a contract" would misclassify a plain
wallet using account abstraction as a smart contract. Confirmed live
2026-07-02 against vitalik.eth's own address, which is currently
EIP-7702-delegated to Ambire's smart-account implementation
(verified-contract name "AmbireAccount7702").

get_verified_contract_name() uses Etherscan's getsourcecode action (free
with the existing ETHERSCAN_API_KEY, no separate key or dependency) to
name VERIFIED contracts (e.g. "UniswapV2Router02" -- confirmed live
2026-07-02). Unverified contracts get no name; Etherscan only exposes
this for source-verified addresses, and there's no free API that reliably
names unverified ones.

No separate curated "known DEX/bridge" address table: OFAC's SDN list
(already downloaded/cached by ofac_sdn.py) already covers the
investigation-relevant sanctioned-mixer case (e.g. Tornado Cash's pool
contracts) for free, without hand-maintaining a second list that would
drift out of date and risks transcription errors from addresses typed
by hand instead of pulled from an authoritative source.
"""

from __future__ import annotations

from typing import Any

import requests

from enrichment.providers._evm_rpc import rpc_call

_EIP7702_DELEGATION_PREFIX = bytes.fromhex("ef0100")
_EIP7702_DELEGATION_LENGTH = 23  # 3-byte prefix + 20-byte address

_ETHERSCAN_API_ROOT = "https://api.etherscan.io/v2/api"
_ETHERSCAN_CHAIN_ID = 1
_ETHERSCAN_TIMEOUT_SECONDS = 10


def _eth_get_code(address: str) -> bytes:
    result = rpc_call("eth_getCode", [address, "latest"])
    if not result or result == "0x":
        return b""
    return bytes.fromhex(result[2:])


def classify_address(address: str) -> dict[str, Any]:
    """Returns {"kind": "eoa"|"contract"|"delegated_eoa", "delegate_address": "0x..."|None, "error": str|None}.

    "delegated_eoa" is still an EOA (has a private key, can be seeded
    from a seed phrase) that has opted into EIP-7702 delegation -- treat
    it like an EOA for classification purposes, but the delegate address
    is worth surfacing since it tells you what smart-account
    implementation the wallet is using.
    """
    try:
        code = _eth_get_code(address)
    except Exception as exc:
        return {"kind": None, "delegate_address": None, "error": f"contract detection failed: {exc}"}

    if not code:
        return {"kind": "eoa", "delegate_address": None, "error": None}
    if len(code) == _EIP7702_DELEGATION_LENGTH and code[:3] == _EIP7702_DELEGATION_PREFIX:
        return {"kind": "delegated_eoa", "delegate_address": "0x" + code[3:].hex(), "error": None}
    return {"kind": "contract", "delegate_address": None, "error": None}


def get_verified_contract_name(address: str, key: str) -> str | None:
    """Etherscan-verified contract name (e.g. "UniswapV2Router02"), or
    None if unverified/not a contract/lookup failed. Silent on failure
    (returns None) -- this is a "nice to have" label, not something
    callers should have to handle as an error case."""
    if not key:
        return None
    try:
        response = requests.get(
            _ETHERSCAN_API_ROOT,
            params={
                "chainid": _ETHERSCAN_CHAIN_ID,
                "module": "contract",
                "action": "getsourcecode",
                "address": address,
                "apikey": key,
            },
            timeout=_ETHERSCAN_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        result = response.json().get("result", [{}])
        name = result[0].get("ContractName", "") if result else ""
        return name or None
    except Exception:
        return None


def tag_address(address: str, key: str) -> dict[str, Any]:
    """Combined classification + verified name, for a single address'
    own report (core_ops._run_evm_staged). Not used per-node during a
    graph walk -- see graph.py, which only does the free classify_address()
    check for each node to stay within Etherscan's rate limit on a
    multi-node walk."""
    classification = classify_address(address)
    contract_name = None
    if classification["kind"] in ("contract", "delegated_eoa"):
        lookup_address = classification["delegate_address"] or address
        contract_name = get_verified_contract_name(lookup_address, key)
    return {**classification, "contract_name": contract_name}

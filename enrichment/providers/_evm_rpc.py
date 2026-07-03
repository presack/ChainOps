"""Shared free public Ethereum JSON-RPC infrastructure -- endpoint
fallback list and a generic eth_call wrapper. Used by ens.py (ENS
resolution) and contract_info.py (contract detection); no API key
required, unlike Etherscan itself.
"""

from __future__ import annotations

from typing import Any

import requests

RPC_TIMEOUT_SECONDS = 10

# Public, free, keyless RPC endpoints, tried in order. Public RPC uptime
# varies in practice (llamarpc.com returned a bare 521 during live
# testing), so a short fallback list is worth the extra lines.
RPC_ENDPOINTS = [
    "https://ethereum.publicnode.com",
    "https://cloudflare-eth.com",
    "https://1rpc.io/eth",
]


def rpc_call(method: str, params: list[Any]) -> Any:
    """Generic JSON-RPC call with endpoint fallback. Returns the `result`
    field; raises RuntimeError if every endpoint fails."""
    last_error: Exception | None = None
    for rpc_url in RPC_ENDPOINTS:
        try:
            payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
            response = requests.post(rpc_url, json=payload, timeout=RPC_TIMEOUT_SECONDS)
            response.raise_for_status()
            body = response.json()
            if "error" in body:
                raise RuntimeError(body["error"].get("message", "RPC error"))
            return body.get("result")
        except Exception as exc:  # noqa: BLE001 -- fall through to the next RPC endpoint on any failure
            last_error = exc
            continue
    raise RuntimeError(f"all RPC endpoints failed: {last_error}")

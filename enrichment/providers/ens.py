"""ENS name resolution -- raw ENS Registry + Resolver contract calls via a
free public Ethereum JSON-RPC endpoint, no API key required.

Deliberately not using web3.py: it pulls in eth-abi/eth-account/eth-utils/
hexbytes and a much heavier dependency tree for what's really two
`eth_call`s plus a keccak256/namehash. pycryptodome (a light, audited,
compiled dependency) supplies the one primitive stdlib doesn't: Ethereum's
original Keccak-256, which is NOT the same as NIST's standardized
SHA3-256 that hashlib.sha3_256 implements (different padding byte) -- a
well-known gotcha that would silently produce wrong hashes if missed.

Live-verified 2026-07-02: resolve_ens("vitalik.eth") returns
0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045, the checksummed form of the
address used throughout this project as the ETH demo target -- keccak256,
namehash, and the EIP-55 checksum were each independently verified against
known reference vectors before this went into the resolution pipeline.
"""

from __future__ import annotations

from Crypto.Hash import keccak

from enrichment.providers._evm_rpc import rpc_call

_ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1E"
_ZERO_ADDRESS = "0x" + "00" * 20


def keccak256(data: bytes) -> bytes:
    k = keccak.new(digest_bits=256)
    k.update(data)
    return k.digest()


def namehash(name: str) -> bytes:
    """EIP-137 namehash: iteratively hash labels right-to-left starting
    from 32 zero bytes."""
    node = b"\x00" * 32
    if name:
        for label in reversed(name.split(".")):
            node = keccak256(node + keccak256(label.encode("utf-8")))
    return node


def to_checksum_address(address: str) -> str:
    """EIP-55 mixed-case checksum, for consistent display."""
    addr = address.lower().replace("0x", "")
    hash_hex = keccak256(addr.encode("ascii")).hex()
    checksummed = "0x"
    for i, char in enumerate(addr):
        if char in "0123456789":
            checksummed += char
        else:
            checksummed += char.upper() if int(hash_hex[i], 16) >= 8 else char
    return checksummed


def _selector(signature: str) -> bytes:
    return keccak256(signature.encode("utf-8"))[:4]


_RESOLVER_SELECTOR = _selector("resolver(bytes32)")
_ADDR_SELECTOR = _selector("addr(bytes32)")


def _eth_call(to: str, data: bytes) -> bytes:
    result = rpc_call("eth_call", [{"to": to, "data": "0x" + data.hex()}, "latest"])
    if not result or result == "0x":
        return b""
    return bytes.fromhex(result[2:])


def resolve_ens(name: str) -> dict:
    """Resolve an ENS name to a checksummed ETH address.

    Returns {"address": "0x...", "error": None} on success, or
    {"address": None, "error": "..."} if the name isn't registered, has no
    resolver, has no ETH address set, or every RPC endpoint failed.
    """
    node = namehash(name)
    try:
        resolver_result = _eth_call(_ENS_REGISTRY, _RESOLVER_SELECTOR + node)
    except Exception as exc:
        return {"address": None, "error": f"ENS registry lookup failed: {exc}"}

    resolver_address = "0x" + resolver_result[-20:].hex() if len(resolver_result) >= 20 else ""
    if not resolver_address or resolver_address.lower() == _ZERO_ADDRESS.lower():
        return {"address": None, "error": f"'{name}' has no resolver set (likely unregistered)"}

    try:
        addr_result = _eth_call(resolver_address, _ADDR_SELECTOR + node)
    except Exception as exc:
        return {"address": None, "error": f"ENS resolver lookup failed: {exc}"}

    resolved_address = "0x" + addr_result[-20:].hex() if len(addr_result) >= 20 else ""
    if not resolved_address or resolved_address.lower() == _ZERO_ADDRESS.lower():
        return {"address": None, "error": f"'{name}' is registered but has no ETH address set"}

    return {"address": to_checksum_address(resolved_address), "error": None}

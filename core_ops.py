"""Core investigative operations for ChainOps.

Phase 0: chain-aware target classification (classify_target) — no network
calls, just decides *what kind of thing* a string is.

Phase 1: run_all_staged() dispatches the free BTC providers in parallel
and folds in first/last-seen + dormancy computed from full tx history.
"""

from __future__ import annotations

import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH32_ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32_CONST = 1
BECH32M_CONST = 0x2BC830A3

_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_DIGITS_RE = re.compile(r"^[0-9]+$")
_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ENS_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.eth$", re.IGNORECASE)


class TargetType:
    BTC_P2PKH = "btc_address_p2pkh"
    BTC_P2SH = "btc_address_p2sh"
    BTC_BECH32 = "btc_address_bech32"
    BTC_TAPROOT = "btc_address_taproot"
    BTC_TXID = "btc_txid"
    BLOCK_HEIGHT = "block_height"
    ETH_ADDRESS = "eth_address"
    ENS_NAME = "ens_name"
    TRON_ADDRESS = "tron_address"
    UNKNOWN = "unknown"


class Chain:
    BITCOIN = "bitcoin"
    ETHEREUM = "ethereum"
    TRON = "tron"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassifiedTarget:
    target: str
    chain: str
    target_type: str
    valid: bool
    detail: str | None = None


def _base58_decode(s: str) -> bytes | None:
    n = 0
    for char in s:
        index = BASE58_ALPHABET.find(char)
        if index == -1:
            return None
        n = n * 58 + index

    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""

    leading_zeros = 0
    for char in s:
        if char != "1":
            break
        leading_zeros += 1

    return b"\x00" * leading_zeros + body


def _base58check_decode(s: str) -> tuple[int, bytes] | None:
    """Return (version_byte, payload) if s is a valid base58check string."""
    raw = _base58_decode(s)
    if raw is None or len(raw) < 5:
        return None
    payload, checksum = raw[:-4], raw[-4:]
    digest = hashlib.sha256(hashlib.sha256(payload).digest()).digest()
    if digest[:4] != checksum:
        return None
    return payload[0], payload[1:]


def _bech32_polymod(values: list[int]) -> int:
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_decode(bech: str) -> tuple[str, list[int], int] | None:
    """Return (hrp, data_values, const) for a valid bech32/bech32m string."""
    if any(ord(c) < 33 or ord(c) > 126 for c in bech):
        return None
    if bech.lower() != bech and bech.upper() != bech:
        return None
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech) or len(bech) > 90:
        return None
    hrp, data_part = bech[:pos], bech[pos + 1 :]
    if any(c not in BECH32_ALPHABET for c in data_part):
        return None
    data = [BECH32_ALPHABET.find(c) for c in data_part]
    const = _bech32_polymod(_bech32_hrp_expand(hrp) + data)
    if const not in (BECH32_CONST, BECH32M_CONST):
        return None
    return hrp, data[:-6], const


def _convertbits(data: list[int], frombits: int, tobits: int, pad: bool = True) -> list[int] | None:
    acc, bits, ret = 0, 0, []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def _classify_btc_bech32(target: str) -> ClassifiedTarget | None:
    decoded = _bech32_decode(target)
    if decoded is None:
        return None
    hrp, data, const = decoded
    if hrp != "bc" or not data:
        return None
    witver = data[0]
    witprog = _convertbits(data[1:], 5, 8, False)
    if witprog is None or not (2 <= len(witprog) <= 40):
        return None
    if witver == 0:
        if const != BECH32_CONST or len(witprog) not in (20, 32):
            return None
        return ClassifiedTarget(target, Chain.BITCOIN, TargetType.BTC_BECH32, True, "segwit v0 (P2WPKH/P2WSH)")
    if 1 <= witver <= 16:
        if const != BECH32M_CONST:
            return None
        if witver == 1 and len(witprog) == 32:
            return ClassifiedTarget(target, Chain.BITCOIN, TargetType.BTC_TAPROOT, True, "segwit v1 (P2TR)")
        return ClassifiedTarget(target, Chain.BITCOIN, TargetType.BTC_BECH32, True, f"segwit v{witver}")
    return None


def _classify_btc_base58(target: str) -> ClassifiedTarget | None:
    decoded = _base58check_decode(target)
    if decoded is None:
        return None
    version, payload = decoded
    if len(payload) != 20:
        return None
    if version == 0x00:
        return ClassifiedTarget(target, Chain.BITCOIN, TargetType.BTC_P2PKH, True, "mainnet P2PKH")
    if version == 0x05:
        return ClassifiedTarget(target, Chain.BITCOIN, TargetType.BTC_P2SH, True, "mainnet P2SH")
    return None


def _classify_tron(target: str) -> ClassifiedTarget | None:
    if not target.startswith("T"):
        return None
    decoded = _base58check_decode(target)
    if decoded is None:
        return None
    version, payload = decoded
    if version != 0x41 or len(payload) != 20:
        return None
    return ClassifiedTarget(target, Chain.TRON, TargetType.TRON_ADDRESS, True)


def classify_target(target: str) -> ClassifiedTarget:
    """Classify a query target across supported chains.

    Order matters: cheap/unambiguous checks first (ENS, ETH, block height,
    txid), then the base58/bech32 decodes that double as validation.
    """
    target = target.strip()

    if _ENS_RE.match(target):
        return ClassifiedTarget(target, Chain.ETHEREUM, TargetType.ENS_NAME, True)

    if _ETH_ADDRESS_RE.match(target):
        return ClassifiedTarget(target, Chain.ETHEREUM, TargetType.ETH_ADDRESS, True)

    if _HEX64_RE.match(target):
        return ClassifiedTarget(target, Chain.BITCOIN, TargetType.BTC_TXID, True)

    if _DIGITS_RE.match(target) and len(target) <= 9:
        return ClassifiedTarget(target, Chain.BITCOIN, TargetType.BLOCK_HEIGHT, True)

    if target.lower().startswith("bc1"):
        result = _classify_btc_bech32(target)
        if result:
            return result
        return ClassifiedTarget(target, Chain.BITCOIN, TargetType.UNKNOWN, False, "malformed bech32 address")

    if target.startswith("T") and len(target) == 34:
        result = _classify_tron(target)
        if result:
            return result
        return ClassifiedTarget(target, Chain.TRON, TargetType.UNKNOWN, False, "malformed Tron address")

    if target and target[0] in "13":
        result = _classify_btc_base58(target)
        if result:
            return result
        return ClassifiedTarget(target, Chain.BITCOIN, TargetType.UNKNOWN, False, "malformed base58 address")

    return ClassifiedTarget(target, Chain.UNKNOWN, TargetType.UNKNOWN, False, "unrecognized target format")


BTC_ADDRESS_TYPES = {
    TargetType.BTC_P2PKH,
    TargetType.BTC_P2SH,
    TargetType.BTC_BECH32,
    TargetType.BTC_TAPROOT,
}

_SECONDS_PER_DAY = 86400


def run_all_staged(target: str, on_update: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Chain-aware staged query: classify target, dispatch the free BTC
    providers in parallel, and fold in first/last-seen + dormancy computed
    from full tx history. Phase 1 MVP — BTC addresses only.

    on_update, if given, is called with a snapshot dict after each stage
    completes (progressive reporting, same pattern as StealthOps'
    run_all_staged), letting a console/web caller render results as they
    arrive instead of waiting for everything.
    """

    def emit(snapshot: dict[str, Any]) -> None:
        if not on_update:
            return
        try:
            on_update(dict(snapshot))
        except Exception:
            pass

    classified = classify_target(target)
    out: dict[str, Any] = {
        "target": classified.target,
        "chain": classified.chain,
        "target_type": classified.target_type,
        "valid": classified.valid,
    }
    if not classified.valid:
        out["error"] = classified.detail
        emit(out)
        return out
    emit(out)

    if classified.chain == Chain.BITCOIN and classified.target_type in BTC_ADDRESS_TYPES:
        return _run_bitcoin_staged(classified.target, out, emit)

    if classified.chain == Chain.TRON and classified.target_type == TargetType.TRON_ADDRESS:
        return _run_tron_staged(classified.target, out, emit)

    if classified.chain == Chain.ETHEREUM and classified.target_type == TargetType.ETH_ADDRESS:
        return _run_evm_staged(classified.target, out, emit)

    if classified.chain == Chain.ETHEREUM and classified.target_type == TargetType.ENS_NAME:
        return _run_ens_staged(classified.target, out, emit)

    out["error"] = (
        "run_all_staged currently only supports BTC, Tron, and ETH address targets; "
        f"got chain={classified.chain} target_type={classified.target_type}"
    )
    emit(out)
    return out


def _run_bitcoin_staged(address: str, out: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    # Deferred import: enrichment.providers._shared imports from core_ops,
    # so importing at module load time would be circular.
    from enrichment.providers import blockstream, ofac_sdn, price, walletexplorer

    with ThreadPoolExecutor(max_workers=4) as pool:
        blockstream_future = pool.submit(blockstream.run, address, "")
        price_future = pool.submit(price.run, address, "")
        walletexplorer_future = pool.submit(walletexplorer.run, address, "")
        ofac_future = pool.submit(ofac_sdn.run, address, "")

        blockstream_data = blockstream_future.result()
        out["blockstream"] = blockstream_data
        emit(out)

        out["price"] = price_future.result()
        emit(out)

        out["walletexplorer"] = walletexplorer_future.result()
        emit(out)

        out["ofac_sdn"] = ofac_future.result()
        emit(out)

    if "error" not in blockstream_data:
        try:
            tx_history = blockstream.fetch_tx_history(address)
        except Exception as exc:
            out["tx_history_error"] = f"could not fetch full tx history: {exc}"
        else:
            confirmed_times = [
                tx["status"]["block_time"] for tx in tx_history if tx.get("status", {}).get("confirmed")
            ]
            first_seen = min(confirmed_times) if confirmed_times else None
            last_seen = max(confirmed_times) if confirmed_times else None
            out["first_seen"] = first_seen
            out["last_seen"] = last_seen
            out["dormancy_days"] = round((time.time() - last_seen) / _SECONDS_PER_DAY, 1) if last_seen else None

    emit(out)
    return out


def _run_ens_staged(name: str, out: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Resolve an ENS name to an ETH address, then run the same staged EVM
    query as a direct address lookup. `out["target"]` stays the ENS name
    the user typed (for display); the resolved address is stamped onto
    `out["resolved_address"]` and is what every downstream provider call
    actually queries.
    """
    from enrichment.providers.ens import resolve_ens

    resolution = resolve_ens(name)
    if resolution["error"]:
        out["error"] = resolution["error"]
        emit(out)
        return out

    resolved_address = resolution["address"]
    out["resolved_address"] = resolved_address
    emit(out)
    return _run_evm_staged(resolved_address, out, emit)


def _run_evm_staged(address: str, out: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    # Deferred import: enrichment.providers._shared imports from core_ops,
    # so importing at module load time would be circular.
    import keystore
    from enrichment.providers import contract_info, evm, ofac_sdn, price

    key = keystore.get_key("ETHERSCAN_API_KEY")

    with ThreadPoolExecutor(max_workers=4) as pool:
        evm_future = pool.submit(evm.run, address, key)
        price_future = pool.submit(price.run, address, "")
        ofac_future = pool.submit(ofac_sdn.run, address, "")
        contract_future = pool.submit(contract_info.tag_address, address, key)

        evm_data = evm_future.result()
        out["evm"] = evm_data
        emit(out)

        out["price"] = price_future.result()
        emit(out)

        out["ofac_sdn"] = ofac_future.result()
        emit(out)

        out["contract_info"] = contract_future.result()
        emit(out)

    if "error" not in evm_data:
        out["last_seen"] = evm_data.get("last_seen")
        try:
            first_seen = evm.fetch_first_seen(address, key)
        except Exception as exc:
            out["tx_history_error"] = f"could not fetch first-seen timestamp: {exc}"
        else:
            out["first_seen"] = first_seen
            out["dormancy_days"] = (
                round((time.time() - out["last_seen"]) / _SECONDS_PER_DAY, 1) if out["last_seen"] else None
            )

    emit(out)
    return out


def _run_tron_staged(address: str, out: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    # Deferred import: enrichment.providers._shared imports from core_ops,
    # so importing at module load time would be circular.
    import keystore
    from enrichment.providers import ofac_sdn, price, tron

    key = keystore.get_key("TRONGRID_API_KEY")

    with ThreadPoolExecutor(max_workers=3) as pool:
        tron_future = pool.submit(tron.run, address, key)
        price_future = pool.submit(price.run, address, "")
        ofac_future = pool.submit(ofac_sdn.run, address, "")

        tron_data = tron_future.result()
        out["tron"] = tron_data
        emit(out)

        out["price"] = price_future.result()
        emit(out)

        out["ofac_sdn"] = ofac_future.result()
        emit(out)

    if "error" not in tron_data:
        try:
            transfer_history = tron.fetch_usdt_transfer_history(address, key)
        except Exception as exc:
            out["tx_history_error"] = f"could not fetch full USDT transfer history: {exc}"
        else:
            # block_timestamp is milliseconds; run_all_staged works in seconds throughout.
            timestamps = [
                t["block_timestamp"] / 1000 for t in transfer_history if t.get("block_timestamp") is not None
            ]
            first_seen = min(timestamps) if timestamps else None
            last_seen = max(timestamps) if timestamps else None
            out["first_seen"] = first_seen
            out["last_seen"] = last_seen
            out["dormancy_days"] = round((time.time() - last_seen) / _SECONDS_PER_DAY, 1) if last_seen else None

    emit(out)
    return out

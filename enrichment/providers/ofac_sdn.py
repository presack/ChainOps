"""OFAC SDN list adapter — flags exact matches against sanctioned digital
currency addresses.

The SDN "advanced XML" export is ~125MB (verified 2026-07-02), so this
does NOT download on every run() call. load_addresses() downloads once on
first use and caches the extracted address lists to disk; refresh() is a
separate, explicit force-refresh meant to be called from a periodic job
(same pattern as StealthOps' updater.py), not from the per-query path.

Schema verified directly against a live download of sdn_advanced.xml:
  ReferenceValueSets/FeatureTypeValues/FeatureType   -- text "Digital
      Currency Address - <ASSET>", ID attribute is the FeatureTypeID
  //Feature[@FeatureTypeID=<id>]/FeatureVersion/VersionDetail -- the
      address text
"""

from __future__ import annotations

import json
import os
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests

from core_ops import Chain, classify_target
from enrichment.providers._shared import error_result

_SDN_XML_URL = "https://www.treasury.gov/ofac/downloads/sanctions/1.0/sdn_advanced.xml"
_DOWNLOAD_TIMEOUT_SECONDS = 180

_NAMESPACE = {"sdn": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ADVANCED_XML"}

_ASSET_CODES = {
    Chain.BITCOIN: "XBT",
    Chain.ETHEREUM: "ETH",
    Chain.TRON: "TRX",
}


def _cache_path() -> str:
    return os.environ.get("OFAC_SDN_CACHE_PATH", os.path.join("cache", "ofac_sdn_addresses.json"))


def _feature_type_id(root: ET.Element, asset_code: str) -> str | None:
    text = f"Digital Currency Address - {asset_code}"
    el = root.find(f"sdn:ReferenceValueSets/sdn:FeatureTypeValues/*[.='{text}']", _NAMESPACE)
    return el.attrib["ID"] if el is not None else None


def extract_addresses(xml_bytes: bytes, asset_codes: list[str]) -> dict[str, list[str]]:
    """Pure parsing step: SDN XML bytes -> {asset_code: [address, ...]}."""
    root = ET.fromstring(xml_bytes)
    result: dict[str, list[str]] = {}
    for asset_code in asset_codes:
        feature_type_id = _feature_type_id(root, asset_code)
        if feature_type_id is None:
            result[asset_code] = []
            continue
        addresses = []
        for feature in root.findall(f".//sdn:Feature[@FeatureTypeID='{feature_type_id}']", _NAMESPACE):
            for detail in feature.findall(".//sdn:VersionDetail", _NAMESPACE):
                if detail.text and detail.text.strip():
                    addresses.append(detail.text.strip())
        result[asset_code] = addresses
    return result


def download_sdn_xml() -> bytes:
    response = requests.get(_SDN_XML_URL, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content


def refresh(asset_codes: list[str] | None = None) -> dict[str, Any]:
    """Force a fresh download + parse + on-disk cache write."""
    asset_codes = asset_codes or sorted(set(_ASSET_CODES.values()))
    xml_bytes = download_sdn_xml()
    addresses = extract_addresses(xml_bytes, asset_codes)
    payload = {"downloaded_at": int(time.time()), "addresses": addresses}

    path = _cache_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)
    return payload


def _load_cache() -> dict[str, Any] | None:
    try:
        with open(_cache_path()) as f:
            return json.load(f)
    except Exception:
        return None


def load_addresses() -> dict[str, Any]:
    """Return cached SDN address data, downloading once if no cache exists.

    Does not re-download just because the cache is old -- call refresh()
    explicitly (e.g. from a scheduled job) to pick up list updates.
    """
    cached = _load_cache()
    if cached is not None:
        return cached
    return refresh()


def run(target: str, key: str) -> dict[str, Any]:
    classified = classify_target(target)
    if not classified.valid:
        return error_result("ofac_sdn", f"unrecognized target: {classified.detail}", classified.target_type)

    asset_code = _ASSET_CODES.get(classified.chain)
    if asset_code is None:
        return error_result(
            "ofac_sdn",
            f"no OFAC SDN digital-currency asset code for chain {classified.chain}",
            classified.target_type,
        )

    try:
        cache_data = load_addresses()
    except Exception as exc:
        return {
            "source": "ofac_sdn",
            "chain": classified.chain,
            "address": classified.target,
            "checked": False,
            "error": f"OFAC SDN list unavailable: {exc}",
        }

    sanctioned_addresses = {a.lower() for a in cache_data.get("addresses", {}).get(asset_code, [])}
    sanctioned = classified.target.lower() in sanctioned_addresses

    return {
        "source": "ofac_sdn",
        "chain": classified.chain,
        "address": classified.target,
        "checked": True,
        "sanctioned": sanctioned,
        "list_downloaded_at": cache_data.get("downloaded_at"),
    }


def check_addresses(addresses: list[str], chain: str) -> dict[str, bool]:
    """Batch-check many addresses against the cached SDN list for one
    chain in a single cache load, instead of calling run() per address
    (which would re-check chain validity and re-read the cache file each
    time). Used by graph.py to flag sanctioned nodes discovered during a
    walk -- free and local once the cache is populated, no extra network
    calls per node. Addresses not found in the SDN list (including if the
    cache itself is unavailable) are reported as not sanctioned rather
    than raising, since a walk shouldn't fail outright over this.
    """
    asset_code = _ASSET_CODES.get(chain)
    if asset_code is None:
        return {addr: False for addr in addresses}

    try:
        cache_data = load_addresses()
    except Exception:
        return {addr: False for addr in addresses}

    sanctioned_addresses = {a.lower() for a in cache_data.get("addresses", {}).get(asset_code, [])}
    return {addr: addr.lower() in sanctioned_addresses for addr in addresses}


def summary(payload: dict[str, Any]) -> str:
    if not payload.get("checked", False):
        return f"ofac_sdn error={payload.get('error', 'unavailable')}"
    return "ofac_sdn SANCTIONED MATCH" if payload["sanctioned"] else "ofac_sdn no match"

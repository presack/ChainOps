"""CoinGecko price adapter — current price and historical price-at-timestamp.

run()/summary() satisfy the standard provider contract (current price of
the target's native chain asset). price_at_timestamp() is a second,
directly-callable function (not part of the run/summary contract) that
run_all_staged() uses to annotate individual tx timestamps with the price
at that time.

CoinGecko's free tier only serves historical data within the trailing 365
days (verified 2026-07-02: querying further back returns error_code
10012, "exceeds the allowed time range" -- paid plans get full history).
price_at_timestamp() surfaces that as an explicit error rather than
silently returning nothing, since for a forensics tool the queried tx is
often years old.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from core_ops import Chain, classify_target
from enrichment.providers._shared import ENRICHMENT_TIMEOUT_SECONDS, error_result, short_http_error

_API_ROOT = "https://api.coingecko.com/api/v3"

_COINGECKO_IDS = {
    Chain.BITCOIN: "bitcoin",
    Chain.ETHEREUM: "ethereum",
    Chain.TRON: "tron",
}

_HISTORY_RANGE_ERROR_CODE = 10012


def run(target: str, key: str) -> dict[str, Any]:
    classified = classify_target(target)
    if not classified.valid:
        return error_result("price", f"unrecognized target: {classified.detail}", classified.target_type)

    coin_id = _COINGECKO_IDS.get(classified.chain)
    if coin_id is None:
        return error_result("price", f"no price mapping for chain {classified.chain}", classified.target_type)

    response = requests.get(
        f"{_API_ROOT}/simple/price",
        params={"ids": coin_id, "vs_currencies": "usd"},
        timeout=ENRICHMENT_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        return error_result("price", short_http_error(response))

    data = response.json()
    usd = data.get(coin_id, {}).get("usd")
    if usd is None:
        return error_result("price", f"no current price data for {coin_id}")

    return {"source": "price", "chain": classified.chain, "coin_id": coin_id, "usd": usd}


def summary(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"price error={payload['error']}"
    return f"price {payload['coin_id']} = ${payload['usd']:,}"


def price_at_timestamp(chain: str, unix_ts: int, key: str = "") -> dict[str, Any]:
    """Historical price of `chain`'s native asset at `unix_ts` (UTC).

    Limited to the trailing 365 days by CoinGecko's free tier -- returns
    an error_result for older timestamps rather than silently failing.
    """
    coin_id = _COINGECKO_IDS.get(chain)
    if coin_id is None:
        return error_result("price", f"no price mapping for chain {chain}")

    date_str = datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%d-%m-%Y")
    response = requests.get(
        f"{_API_ROOT}/coins/{coin_id}/history",
        params={"date": date_str, "localization": "false"},
        timeout=ENRICHMENT_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        try:
            error_code = response.json().get("error", {}).get("status", {}).get("error_code")
        except Exception:
            error_code = None
        if error_code == _HISTORY_RANGE_ERROR_CODE:
            return error_result(
                "price",
                f"historical price for {date_str} unavailable on free tier "
                "(CoinGecko free API only covers the trailing 365 days)",
            )
        return error_result("price", short_http_error(response))

    data = response.json()
    usd = data.get("market_data", {}).get("current_price", {}).get("usd")
    if usd is None:
        return error_result("price", f"no historical price data for {coin_id} on {date_str}")

    return {"source": "price", "chain": chain, "coin_id": coin_id, "date": date_str, "usd": usd}

"""Shared contract and utilities for enrichment provider adapters.

Every enrichment/providers/<name>.py module must export:

    run(target: str, key: str) -> dict
        Query the provider for `target` (a raw target string; the provider
        itself decides whether to reclassify it). `key` is the API key,
        or "" for key-optional/free-tier providers. Must not raise for
        ordinary failure modes (HTTP errors, wrong-chain target) — return
        an error dict instead (see `error_result`). Only let unexpected
        exceptions propagate.

    summary(payload: dict) -> str
        Render the dict from `run()` as a single human-readable line for
        the CLI/console report.

`ProviderModule` below is that contract as a typing.Protocol, for
reference/type-checking — providers are plain modules, not classes, so
nothing has to inherit from it.
"""

from __future__ import annotations

from typing import Any, Protocol

import requests

from core_ops import Chain, ClassifiedTarget, classify_target

ENRICHMENT_TIMEOUT_SECONDS = 10


class ProviderModule(Protocol):
    def run(self, target: str, key: str) -> dict[str, Any]: ...
    def summary(self, payload: dict[str, Any]) -> str: ...


def error_result(source: str, message: str, target_type: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"source": source, "error": message}
    if target_type is not None:
        result["target_type"] = target_type
    return result


def require_chain(target: str, expected_chain: str, source: str) -> ClassifiedTarget | dict[str, Any]:
    """Classify `target` and enforce it belongs to `expected_chain`.

    Returns the ClassifiedTarget on success, or an `error_result()` dict
    a provider's `run()` can return directly — e.g.:

        classified = require_chain(target, Chain.BITCOIN, "blockstream")
        if isinstance(classified, dict):
            return classified
    """
    classified = classify_target(target)
    if not classified.valid:
        return error_result(source, f"unrecognized target: {classified.detail}", classified.target_type)
    if classified.chain != expected_chain:
        return error_result(
            source,
            f"{source} requires a {expected_chain} target, got {classified.chain}",
            classified.target_type,
        )
    return classified


def short_http_error(response: requests.Response) -> str:
    body = response.text.strip().replace("\n", " ")
    if len(body) > 140:
        body = body[:137].rstrip() + "..."
    return f"http {response.status_code}: {body or 'request failed'}"


__all__ = [
    "Chain",
    "ENRICHMENT_TIMEOUT_SECONDS",
    "ProviderModule",
    "error_result",
    "require_chain",
    "short_http_error",
]

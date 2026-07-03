"""Provider key registry: maps ChainOps' key-bearing providers to their
env var names, for `set-key`/`providers` console commands.

Deliberately minimal compared to StealthOps' PROVIDER_SPECS (17 providers)
-- ChainOps has two key-bearing providers today. keystore.py's
get_key/set_key/delete_key already operate on env var names directly (see
its docstring); this is the thin provider-name layer on top of that,
built once a registry was actually needed rather than speculatively.
"""

from __future__ import annotations

from dataclasses import dataclass

import keystore


@dataclass(frozen=True)
class KeyProvider:
    name: str
    display_name: str
    env_var: str
    target_label: str
    required: bool  # True: the provider returns nothing at all without a key


# Order matters for the setup wizard -- required providers first.
KEY_PROVIDERS: dict[str, KeyProvider] = {
    "evm": KeyProvider(
        "evm", "Etherscan (EVM/ETH)", "ETHERSCAN_API_KEY", "ETH address", required=True
    ),
    "tron": KeyProvider(
        "tron", "TronGrid (Tron)", "TRONGRID_API_KEY", "Tron address -- optional, raises the free rate limit",
        required=False,
    ),
}

# Roadmap Phase 4 paid attribution providers -- no adapter code exists for
# any of these yet (deliberately: they're enterprise/B2B APIs, often
# requiring a sales relationship to even see full docs, with no way to
# live-verify a blind implementation -- see ROADMAP.md Phase 4). Listed
# here only so `providers` is honest about what's planned vs. what
# actually works today; NOT in KEY_PROVIDERS, since that would imply
# `set-key` does something useful for them, which it doesn't.
PLANNED_PROVIDERS: list[str] = [
    "Chainalysis",
    "TRM Labs",
    "Elliptic",
    "Arkham Intelligence",
    "Breadcrumbs",
    "Crystal Blockchain",
]


def get_key_status(provider_name: str) -> dict:
    spec = KEY_PROVIDERS[provider_name]
    value = keystore.get_key(spec.env_var)
    return {"spec": spec, "configured": bool(value), "masked": keystore.mask(value)}


def get_all_status() -> dict[str, dict]:
    return {name: get_key_status(name) for name in KEY_PROVIDERS}

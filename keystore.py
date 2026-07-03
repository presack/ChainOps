"""Personal-mode API key storage in a user-writable keys.env file.

Adapted from StealthOps' keystore.py, simplified: ChainOps has no
provider registry yet (StealthOps' version keys everything off
PROVIDER_SPECS from its enrichment.manager, which ChainOps hasn't built),
so this operates directly on env var names rather than provider names.
Once a provider registry exists, a thin provider-name -> env-var lookup
can sit on top of this without changing the storage layer.

Keys are stored as ENV_VAR=value pairs. load_into_environ() is called at
startup to inject file keys into os.environ (existing env vars take
precedence).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _keys_dir() -> Path:
    # CHAINOPS_KEYS_DIR lets WSL2 point at the Windows key store so both
    # the Windows and Linux binaries share the same keys.env file.
    override = os.environ.get("CHAINOPS_KEYS_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(base) / "ChainOps"
    return Path.home() / ".config" / "chainops"


def _keys_file() -> Path:
    return _keys_dir() / "keys.env"


def _read_file() -> dict[str, str]:
    try:
        result: dict[str, str] = {}
        for line in _keys_file().read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key:
                result[key] = value
        return result
    except Exception:
        return {}


def _write_file(data: dict[str, str]) -> None:
    try:
        _keys_dir().mkdir(parents=True, exist_ok=True)
        lines = [f"{k}={v}" for k, v in sorted(data.items()) if v]
        _keys_file().write_text("\n".join(lines) + ("\n" if lines else ""))
    except Exception:
        pass


def load_into_environ() -> None:
    """Inject file keys into os.environ. Existing env vars are not overwritten."""
    for env_var, value in _read_file().items():
        if env_var not in os.environ and value:
            os.environ[env_var] = value


def sync_into_environ() -> None:
    """Re-read the keys file and overwrite os.environ with current values.

    Unlike load_into_environ, this always applies file values so that keys
    changed externally (another terminal, a future web UI process) are
    picked up immediately.
    """
    for env_var, value in _read_file().items():
        if value:
            os.environ[env_var] = value
        else:
            os.environ.pop(env_var, None)


def get_key(env_var: str) -> str:
    """Return the effective value for env_var: live os.environ wins, else file."""
    live = os.environ.get(env_var, "")
    if live:
        return live
    return _read_file().get(env_var, "")


def set_key(env_var: str, value: str) -> None:
    """Save or clear a key for env_var."""
    data = _read_file()
    if value:
        data[env_var] = value
        os.environ[env_var] = value
    else:
        data.pop(env_var, None)
        os.environ.pop(env_var, None)
    _write_file(data)


def delete_key(env_var: str) -> None:
    set_key(env_var, "")


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••••••" + value[-4:]


def run_setup_wizard() -> None:
    """Walk through all key-bearing providers interactively. Saves each
    key immediately; Ctrl+C or 'done' stops early but keeps whatever was
    already saved. Mirrors StealthOps' wizard, scoped to ChainOps' (much
    shorter) provider list.
    """
    # Deferred import: enrichment.providers._registry imports keystore,
    # so importing at module load time would be circular.
    from enrichment.providers._registry import KEY_PROVIDERS, get_key_status

    print("")
    print("  ChainOps API Key Setup")
    print("  " + "-" * 38)
    print("  Press Enter to keep an existing value.")
    print("  Type 'done' to finish early, Ctrl+C to stop and keep saved keys.")
    print("")

    changes = 0
    for provider in KEY_PROVIDERS.values():
        status = get_key_status(provider.name)
        suffix = f" [{status['masked']}]" if status["configured"] else " [not set]"
        required_tag = "" if provider.required else " (optional)"
        prompt = f"  {provider.display_name}{required_tag}{suffix}: "
        try:
            new_val = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            break
        if new_val.lower() == "done":
            break
        if new_val == "":
            continue
        set_key(provider.env_var, new_val)
        changes += 1
        print("  [saved]")

    print("")
    print(f"  {changes} key(s) saved." if changes else "  No changes made.")
    print("")

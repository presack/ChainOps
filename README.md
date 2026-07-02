# ChainOps

A StealthOps-style recon tool for cryptocurrency/blockchain addresses — same philosophy (single-target query → structured report → pivot on anything returned → enrich with third-party providers → bulk triage → PDF report), applied to on-chain graphs instead of DNS/WHOIS/IP infrastructure.

## Why

Manually tracing a wallet — chasing balance, tx history, and neighbor addresses by hand across block explorer and price APIs — takes a dozen ad-hoc curl calls chained together: address → tx → neighbor address → neighbor's tx → repeat. That's the exact same pivot loop StealthOps automates for infrastructure recon (IP → ASN → netblock → related domains). The graph-walk is the product; the block explorer APIs are just the data source.

**Use cases:**

- Tracing stolen/scam funds (romance scams, pig-butchening, ransomware payments) toward a cash-out point
- Building an address cluster for a threat actor / campaign
- AML-style due diligence on a counterparty address before a transaction
- Teaching/training material — same role StealthOps plays in cyber training decks, but for "follow the money" exercises

---

## Install

**Windows** (PowerShell — no admin required):

```powershell
irm https://github.com/presack/ChainOps/releases/latest/download/install.ps1 | iex
```

Installs to `%LOCALAPPDATA%\Programs\ChainOps\`, adds to PATH, and configures the Linux binary in WSL2 automatically. Windows and WSL2 share the same API key store.

**Linux** (x86_64):

```bash
curl -fsSL https://github.com/presack/ChainOps/releases/latest/download/install.sh | bash
```

Installs to `~/.local/bin/`, SHA256-verified. macOS binaries aren't built yet.

After installing, open a new terminal and run:

```
chainops --console
```

---

## Console — interactive mode (primary)

The console keeps session state across commands: query a seed address, then pivot from anything it returns.

```
chainops --console
```

Key commands:

```
# Query
<target>              run a lookup (BTC, Tron, or ETH address)
expand [address]      expand neighbors from address (default: current seed) at the current depth
depth <n>              set hop depth for subsequent expand commands (default: 1)

# Session
graph                  show the accumulated session graph
draw [path]            export the session graph as draw.io XML
status                 show seed, depth, and graph size
reset                  clear the accumulated session graph

# Bulk triage
bulk 8.8.8.8, example.com    inline list (comma or space separated; BTC addresses only for now)
bulk addresses.csv            read from a CSV (bare list, or a header row with an "address" column)
bulk                          paste mode — type addresses, blank line to submit

# Reports (PDF)
report [path]                 PDF case report for the last query
report cluster <id> [path]    PDF cluster report from the last 'bulk' run's triage rows

# Other
banner                 redraw the startup banner
version                show the current version
update                 check for and install an update (built binaries only)
help                   grouped command reference
```

---

## CLI — single-shot queries

```
chainops 1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a
chainops 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 --json
chainops --version
chainops --update
```

ChainOps' running demo/test target is `1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a` — publicly reported (Forbes, 2013) as connected to Ross Ulbricht/Dread Pirate Roberts during the Silk Road seizure. It's long-public, non-sensitive, and has enough real transaction history (150+ txs) to exercise the graph-walk and clustering phases.

---

## Supported chains

| Chain | Address types | Key required |
|---|---|---|
| Bitcoin | P2PKH, P2SH, bech32, taproot | No (Blockstream Esplora, free) |
| Tron | Base58 `T...` | No (TronGrid, free tier) |
| Ethereum | `0x...` | Yes (`ETHERSCAN_API_KEY`) |

Every report also includes current/historical USD price (CoinGecko) and an OFAC SDN sanctions-list check, free and keyless on all three chains. Bitcoin additionally gets free wallet-clustering lookups (WalletExplorer.com).

Set the Etherscan key once via an environment variable, or with the keystore (`keys.env`, same pattern as StealthOps — stored at `%LOCALAPPDATA%\ChainOps\keys.env` on Windows or `~/.config/chainops/keys.env` on Linux).

---

## Graph pivoting

The differentiator over a plain block-explorer lookup: automated multi-hop pivoting from a seed address, with clustering heuristics (common-input-ownership, change-address detection, peel-chain detection) surfaced alongside the raw graph. `expand`/`depth`/`graph`/`draw` in the console drive this — see "Console" above.

---

## Bulk triage & PDF reports

`bulk` (CSV of addresses in, triage columns out — balance, first/last seen, cluster id, sanctions hit, dormancy, risk flags) and `report`/`report cluster` (PDF case reports) are console commands — see "Console" above. Bulk triage is BTC-only for now; results save to `~/Downloads/chainops-bulk-<timestamp>.csv` and feed the session's `report cluster` command. `report` (no `cluster`) generates a PDF for whatever address you last queried.

CLI (single-shot, no console) wiring for both isn't built yet — use the console for now, or call `bulk.py`/`report.py` directly from Python.

---

## Build from source

Requires Python 3.12:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py --console
```

Build standalone binaries:

```powershell
.\scripts\build.ps1              # Windows EXE -> dist\windows\chainops.exe
bash ./scripts/build-linux.sh    # Linux binary -> dist/linux/chainops (run in WSL2)
.\scripts\release.ps1 v1.2.3     # Stamp version, build both, publish GitHub release
```

---

## Non-goals (v1)

- Not a wallet — no key custody, no signing, no send capability
- Not a real-time monitoring/alerting service
- Not a trading or portfolio tool
- Not a replacement for paid attribution platforms (Chainalysis/TRM/Elliptic) — it complements them by doing the free 80% (balances, graph structure, behavioral clustering) and leaving room to plug in a paid provider for the "whose wallet is this" 20%

## License

MIT

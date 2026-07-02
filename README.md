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

Installs to `%LOCALAPPDATA%\Programs\ChainOps\` and adds it to PATH.

> No release has been published yet — until then, use "Build from source" below.

Linux/macOS install isn't built yet (see Roadmap).

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

`bulk.py` (CSV of addresses in, triage columns out — balance, first/last seen, cluster id, sanctions hit, dormancy, risk flags) and `report.py` (PDF case reports) are built and tested, but not yet wired into the console/CLI as user-facing commands — call them directly from Python for now:

```python
from bulk import run_bulk_triage
run_bulk_triage("addresses.csv", "triage.csv")

from report import generate_address_report
from core_ops import run_all_staged
generate_address_report("<address>", run_all_staged("<address>"))
```

Console/CLI wiring for both is on the roadmap.

---

## Build from source

Requires Python 3.12:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py --console
```

Build a standalone Windows binary:

```powershell
.\scripts\build.ps1     # -> dist\windows\chainops.exe
```

Linux binary build is not set up yet (Windows-first; see Roadmap).

---

## Non-goals (v1)

- Not a wallet — no key custody, no signing, no send capability
- Not a real-time monitoring/alerting service
- Not a trading or portfolio tool
- Not a replacement for paid attribution platforms (Chainalysis/TRM/Elliptic) — it complements them by doing the free 80% (balances, graph structure, behavioral clustering) and leaving room to plug in a paid provider for the "whose wallet is this" 20%

## License

MIT

# ChainOps

A StealthOps-style recon tool for cryptocurrency/blockchain addresses — same philosophy (single-target query → structured report → pivot on anything returned → enrich with third-party providers → bulk triage → PDF report), applied to on-chain graphs instead of DNS/WHOIS/IP infrastructure.

## Why

Manually tracing a wallet — chasing balance, tx history, and neighbor addresses by hand across Blockstream, CoinGecko, and WalletExplorer — takes a dozen ad-hoc curl calls chained together: address → tx → neighbor address → neighbor's tx → repeat. That's the exact same pivot loop StealthOps automates for infrastructure recon (IP → ASN → netblock → related domains). The graph-walk is the product; the block explorer APIs are just the data source.

ChainOps' running demo/test target is `1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a` — publicly reported (Forbes, 2013) as connected to Ross Ulbricht/Dread Pirate Roberts during the Silk Road seizure. It's long-public, non-sensitive, and has enough real transaction history (150+ txs) to exercise the graph-walk and clustering phases once they exist.

## Target use cases

- Tracing stolen/scam funds (romance scams, pig-butchening, ransomware payments) toward a cash-out point
- Building an address cluster for a threat actor / campaign
- AML-style due diligence on a counterparty address before a transaction
- Teaching/training material — same role StealthOps plays in the Botswana/Manila cyber training decks, but for "follow the money" exercises

## Non-goals (v1)

- Not a wallet — no key custody, no signing, no send capability
- Not a real-time monitoring/alerting service (no webhooks/watchlists yet — could become a phase-5 idea)
- Not a trading or portfolio tool
- Not a replacement for paid attribution platforms (Chainalysis/TRM/Elliptic) — it complements them by doing the free 80% (balances, graph structure, behavioral clustering) and leaving room to plug in a paid provider for the "whose wallet is this" 20%

## What ports over from StealthOps almost unchanged

- `keystore.py` — local API key storage
- `cache.py` — result caching (even more effective here since confirmed on-chain data never changes)
- `auth.py` — SERVER_MODE accounts + per-user encrypted keys, if a shared/training deployment is wanted later
- `bulk.py` — CSV-in/CSV-out triage
- `report.py` — PDF case reports
- The provider-abstraction contract: each `enrichment/providers/<name>.py` exports `run(target, key) -> dict` and `summary(payload) -> str`

## What's genuinely new

- **Graph-walk engine** — N-hop expansion from a seed address, following tx inputs/outputs (this is the core value-add, no StealthOps analog)
- **Clustering heuristics** — common-input-ownership, change-address detection, peel-chain detection
- **Multi-chain providers** — UTXO model (BTC) vs. account/contract model (EVM chains, Tron) are different enough to need separate query logic, not just a different API key
- **Valuation context** — historical price-at-tx-time + current price (no infra-recon analog)

See `ROADMAP.md` for phased build plan.

# LIQUIDITY LENS

Real-time liquidity and order book imbalance monitor for Vietnamese equities (academic project, not investment advice).

## Setup
```
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

## Run tests
```
pytest -q
```

## Docs
- Spec: [docs/design.md](docs/design.md)
- Plans: [docs/superpowers/plans/](docs/superpowers/plans/)

## Collector (needs SSI_API_KEY and SSI_API_SECRET in the environment)
```
python -m liquidity_lens.collector.main [--symbols watchlist.txt]   # no --symbols: VIC, HPG, FPT; watchlist.txt: 30 VN30 symbols [--db data/liquidity_lens.db]
```
Only HOSE symbols for now (default watchlist: `config.DEFAULT_WATCHLIST`). Ctrl+C flushes and exits cleanly.
Only the collector holds a token (one active session per apiKey); never run it together with `scripts/smoke_test.py`.

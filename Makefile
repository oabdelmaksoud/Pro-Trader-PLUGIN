# CooperCorp PRJ-002 — Makefile
# Usage: make <target>

PYTHON = python3
REPO_DIR = /Users/omarabdelmaksoud/.openclaw/workspace/prj-002/coopercorp-trading

.PHONY: help status test backtest performance signals accounts reconcile rotate-logs analyze

help:
	@echo "CooperCorp PRJ-002 — Available commands:"
	@echo "  make status       — Account health check"
	@echo "  make test         — Run pytest suite"
	@echo "  make backtest     — Replay signals vs actual prices (last 30 days)"
	@echo "  make performance  — P&L stats from ledger"
	@echo "  make signals      — Signal accuracy report"
	@echo "  make reconcile    — Detect orphaned positions"
	@echo "  make rotate       — Rotate old logs (90-day window)"
	@echo "  make analyze T=NVDA — Full LangGraph analysis on ticker"
	@echo "  make gate T=NVDA A=BUY S=7.8 C=8 — Execute through trade gate (dry-run)"

status:
	$(PYTHON) scripts/account_status.py

test:
	$(PYTHON) -m pytest tests/ -v

backtest:
	$(PYTHON) scripts/backtest.py --days 30

performance:
	$(PYTHON) scripts/performance.py

signals:
	$(PYTHON) scripts/signal_accuracy.py

reconcile:
	$(PYTHON) scripts/reconcile_positions.py

rotate:
	$(PYTHON) scripts/rotate_logs.py

analyze:
	$(PYTHON) scripts/analyze.py --ticker $(T)

gate:
	$(PYTHON) scripts/trade_gate.py --ticker $(T) --action $(A) --score $(S) --conviction $(C) --analysis "Manual test" --scan-time "manual" --dry-run

equity:
	$(PYTHON) scripts/equity_snapshot.py

weekly:
	$(PYTHON) scripts/weekly_review.py

#!/usr/bin/env python3
"""NVDA $250C Apr17 live position tracker using Alpaca real-time options data."""

import os, sys
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.openclaw/workspace/prj-002/coopercorp-trading/.env"))

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest, StockLatestQuoteRequest

SYMBOL = "NVDA260417C00250000"
CONTRACTS = 168
COST_BASIS = 7056.0  # $0.42 x 168 x 100

def run():
    opt_client = OptionHistoricalDataClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"]
    )
    stk_client = StockHistoricalDataClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"]
    )

    # Live option snapshot
    snap = opt_client.get_option_snapshot(OptionSnapshotRequest(symbol_or_symbols=[SYMBOL]))
    data = snap[SYMBOL]

    bid = data.latest_quote.bid_price
    ask = data.latest_quote.ask_price
    mid = round((bid + ask) / 2, 4)
    greeks = data.greeks
    iv = round(data.implied_volatility * 100, 2)

    # Live stock quote
    stk = stk_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=["NVDA"]))
    nvda_bid = stk["NVDA"].bid_price
    nvda_ask = stk["NVDA"].ask_price
    nvda_price = round((nvda_bid + nvda_ask) / 2, 2)

    position_value = round(mid * CONTRACTS * 100, 2)
    pnl = round(position_value - COST_BASIS, 2)
    pnl_pct = round((pnl / COST_BASIS) * 100, 2)
    pnl_sign = "+" if pnl >= 0 else ""

    # Action logic
    if pnl_pct >= 80:
        action = "🟢 TAKE PROFIT"
    elif pnl_pct <= -40:
        action = "🔴 CUT — salvage remaining premium"
    elif nvda_price < 178:
        action = "🔴 CUT — NVDA below key support"
    elif nvda_price > 190:
        action = "🟡 HOLD — momentum building"
    else:
        action = "🟡 HOLD — monitor closely"

    msg = f"""📊 **NVDA $250C Apr17 — Live Update**
📍 NVDA: ${nvda_price}
🔢 Contract: ${mid} (bid ${bid} / ask ${ask})
📐 Δ {greeks.delta:.4f} | θ {greeks.theta:.4f} | ν {greeks.vega:.4f} | IV {iv}%
💰 Value: ${position_value:,.2f} | P&L: {pnl_sign}${abs(pnl):,.2f} ({pnl_sign}{pnl_pct}%)
⚡ {action}"""

    print(msg)
    return msg

if __name__ == "__main__":
    run()

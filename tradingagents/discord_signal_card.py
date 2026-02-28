"""
CooperCorp PRJ-002 — Signal Card Formatter
Generates the standardized signal card format for all Discord posts.

Format example:
🟢 E-MINI S&P 500 FUTURES LONG
Current Price: $690.36
24h Change: -0.49%
```
$ 703 ┤┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈ ◀ T2 $701.18
$ 698 ┤┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈ ◀ T1 $696.85
$ 693 ┤              ╭─╮
$ 689 ┤┈┈┈┈┈┈┈┈┈┈╭───╮┈╭─╯┈╰─● ● Today | ◀ Entry $690.36
$ 684 ┤╭─────╮┈┈┈│┈┈┈╰─╯┈┈┈┈┈┈ ◀ Stop $686.03
$ 679 ┤╯     │ ╭─╯
$ 675 ┤      │ │
$ 670 ┤      ╰─╯
      └───────────────────────
```
"""
import math
from typing import Optional
import yfinance as yf


def _fetch_recent_closes(symbol: str, bars: int = 24) -> list:
    """Fetch recent close prices for ASCII chart — intraday 30m bars for today's detail."""
    sym_map = {
        "ES": "ES=F", "NQ": "NQ=F", "YM": "YM=F", "RTY": "RTY=F",
        "GC": "GC=F", "CL": "CL=F", "BTC": "BTC-USD", "SPX": "^GSPC",
    }
    sym = sym_map.get(symbol.upper(), symbol)
    try:
        tk = yf.Ticker(sym)
        # Try 30-min bars first (best intraday detail)
        hist = tk.history(period="5d", interval="30m")
        if len(hist) >= 8:
            return list(hist["Close"].tail(bars))
        # Fall back to 1h
        hist = tk.history(period="5d", interval="1h")
        if len(hist) >= 4:
            return list(hist["Close"].tail(bars))
        # Fall back to daily
        hist = tk.history(period="30d", interval="1d")
        return list(hist["Close"].tail(bars))
    except Exception:
        return []


def _draw_ascii_chart(
    prices: list,
    entry: float,
    stop: float,
    t1: float,
    t2: Optional[float],
    current: float,
    width: int = 24,
    height: int = 8,
) -> str:
    """
    Draw an ASCII price chart with annotated levels.
    Returns multi-line string (without code fences).
    """
    if not prices:
        prices = [current]

    # Price range: encompass BOTH key levels AND actual historical prices
    key_levels = [entry, stop, t1, current]
    if t2:
        key_levels.append(t2)
    all_prices = prices + key_levels
    data_min = min(all_prices)
    data_max = max(all_prices)
    padding = (data_max - data_min) * 0.08  # 8% padding
    top_level = data_max + padding
    bottom_level = data_min - padding
    price_range = top_level - bottom_level
    if price_range == 0:
        price_range = current * 0.1

    # Normalize prices to chart height
    def to_row(price: float) -> int:
        """Convert price to chart row (0=top, height-1=bottom)."""
        normalized = (top_level - price) / price_range
        return max(0, min(height - 1, int(normalized * (height - 1))))

    # Build price labels for each row
    row_prices = []
    for r in range(height):
        p = top_level - (r / (height - 1)) * price_range
        row_prices.append(p)

    # Build chart columns from price data
    # Use last `width` bars, or interpolate if fewer
    chart_prices = prices[-width:] if len(prices) >= width else prices
    # Pad left with first price if shorter
    while len(chart_prices) < width:
        chart_prices = [chart_prices[0]] + chart_prices

    # Determine which horizontal levels touch which rows
    level_rows = {
        to_row(entry): ("entry", entry),
        to_row(stop): ("stop", stop),
        to_row(t1): ("t1", t1),
    }
    if t2:
        level_rows[to_row(t2)] = ("t2", t2)

    # Build the grid
    grid = [[" "] * width for _ in range(height)]

    # Draw price line using box-drawing chars
    prev_row = to_row(chart_prices[0])
    for col, price in enumerate(chart_prices):
        row = to_row(price)
        if col == len(chart_prices) - 1:
            # Current price — mark with ●
            grid[row][col] = "●"
        elif row == prev_row:
            grid[row][col] = "─"
        elif row < prev_row:
            # Price moving up
            grid[row][col] = "╭"
            for r in range(row + 1, prev_row):
                grid[r][col] = "│"
            grid[prev_row][col] = "╯"
        else:
            # Price moving down
            grid[prev_row][col] = "╮"
            for r in range(prev_row + 1, row):
                grid[r][col] = "│"
            grid[row][col] = "╰"
        prev_row = row

    # Render lines
    lines = []
    for r in range(height):
        price_label = f"$ {row_prices[r]:,.0f}"
        # Left pad label to 6 chars
        label = f"{price_label:>7}"
        row_str = "".join(grid[r])

        # Replace spaces with dashes on annotated level rows, up to ●
        level = level_rows.get(r)
        if level:
            level_name, level_price = level
            # Fill spaces with ┈ (dotted line on level rows)
            bullet_pos = row_str.find("●")
            if bullet_pos == -1:
                bullet_pos = width
            new_row = []
            for i, ch in enumerate(row_str):
                if ch == " " and i < bullet_pos:
                    new_row.append("┈")
                else:
                    new_row.append(ch)
            row_str = "".join(new_row)

            # Annotation
            if level_name == "t2":
                annotation = f" ◀ T2 ${level_price:,.2f}"
            elif level_name == "t1":
                annotation = f" ◀ T1 ${level_price:,.2f}"
            elif level_name == "entry":
                annotation = f" ● Today | ◀ Entry ${level_price:,.2f}"
            elif level_name == "stop":
                annotation = f" ◀ Stop ${level_price:,.2f}"
            else:
                annotation = ""
        else:
            annotation = ""

        lines.append(f"{label} ┤{row_str}{annotation}")

    # Bottom axis
    lines.append("       └" + "─" * width)
    return "\n".join(lines)


def format_signal_card(
    symbol: str,
    name: str,
    direction: str,  # "LONG" | "SHORT" | "WATCH"
    current_price: float,
    change_24h: float,
    entry: float,
    stop: float,
    t1: float,
    t2: Optional[float] = None,
    score: Optional[float] = None,
    conviction: Optional[int] = None,
    catalyst: Optional[str] = None,
    notes: Optional[str] = None,
    agent: str = "Cooper 🦅",
) -> str:
    """
    Generate the standardized signal card for Discord.
    Returns a complete formatted string ready to post.
    """
    # Direction emoji
    if direction == "LONG":
        emoji = "🟢"
    elif direction == "SHORT":
        emoji = "🔴"
    elif direction == "WATCH":
        emoji = "🟡"
    elif direction == "EXIT":
        emoji = "⚪"
    else:
        emoji = "⚫"

    # Auto-fetch live change if not provided
    if change_24h == 0.0:
        try:
            sym_map = {"ES": "ES=F", "NQ": "NQ=F", "BTC": "BTC-USD"}
            sym = sym_map.get(symbol.upper(), symbol)
            hist = yf.Ticker(sym).history(period="2d", interval="1d")
            if len(hist) >= 2:
                change_24h = (float(hist["Close"].iloc[-1]) - float(hist["Close"].iloc[-2])) / float(hist["Close"].iloc[-2]) * 100
        except Exception:
            pass
    change_sign = "+" if change_24h >= 0 else ""
    change_str = f"{change_sign}{change_24h:.2f}%"

    # Fetch price history for chart
    prices = _fetch_recent_closes(symbol, bars=22)

    # Build chart
    chart = _draw_ascii_chart(
        prices=prices,
        entry=entry,
        stop=stop,
        t1=t1,
        t2=t2,
        current=current_price,
    )

    # Header
    lines = [
        f"{emoji} {name.upper()} {direction}",
        f"Current Price: ${current_price:,.2f}",
        f"24h Change: {change_str}",
    ]

    if catalyst:
        lines.append(f"Catalyst: {catalyst}")

    # Chart block
    lines.append("```")
    lines.append(chart)
    lines.append("```")

    # Metadata footer
    meta = []
    if score is not None:
        meta.append(f"Score: {score:.1f}/10")
    if conviction is not None:
        meta.append(f"Conviction: {conviction}/10")
    r_r = (t1 - entry) / (entry - stop) if entry != stop else 0
    meta.append(f"R/R: {r_r:.1f}:1")

    if meta:
        lines.append(" | ".join(meta))

    # Options strategies section (multi-strategy)
    try:
        from tradingagents.dataflows.options_chain import get_options_strategies, format_options_block
        from tradingagents.dataflows.iv_percentile import get_iv_rank
        iv_rank = None
        try:
            iv_data = get_iv_rank(symbol)
            iv_rank = iv_data.get("iv_rank")
        except Exception:
            pass
        strategies = get_options_strategies(
            symbol,
            direction=direction,
            current_price=current_price,
            iv_rank=iv_rank,
            score=score if score else 7.0,
        )
        block = format_options_block(strategies)
        if block:
            lines.append("")
            lines.append(block)
    except Exception:
        pass

    if notes:
        lines.append(notes)

    lines.append(f"— {agent} | CooperCorp PRJ-002")

    return "\n".join(lines)


def format_exit_card(
    symbol: str,
    name: str,
    direction: str,  # "LONG" | "SHORT"
    entry_price: float,
    exit_price: float,
    pl_pct: float,
    pl_dollar: float,
    reason: str,
    held_time: Optional[str] = None,
    lesson: Optional[str] = None,
    agent: str = "Executor ⚡",
) -> str:
    """Format a trade exit card."""
    is_win = pl_pct > 0
    result_emoji = "✅" if is_win else "❌"
    direction_emoji = "🟢" if direction == "LONG" else "🔴"
    pl_sign = "+" if pl_pct >= 0 else ""

    lines = [
        f"{result_emoji} {direction_emoji} {name.upper()} CLOSED — {reason}",
        f"Entry: ${entry_price:,.2f} → Exit: ${exit_price:,.2f}",
        f"P&L: {pl_sign}{pl_pct:.2f}% (${pl_sign}{pl_dollar:,.2f})",
    ]

    if held_time:
        lines.append(f"Held: {held_time}")
    if lesson:
        lines.append(f"📝 Lesson: {lesson}")

    lines.append(f"— {agent} | CooperCorp PRJ-002")
    return "\n".join(lines)


def format_watchlist_card(
    items: list,
    scan_time: str,
    agent: str = "Cooper 🦅",
) -> str:
    """
    Format a watchlist/scan card with multiple tickers.
    items: list of dicts with symbol, name, direction, price, change_24h, score, catalyst
    """
    lines = [f"📊 SCAN — {scan_time}", ""]
    for item in items[:5]:  # max 5 per card
        sym = item.get("symbol", "")
        name = item.get("name", sym)
        direction = item.get("direction", "WATCH")
        price = item.get("price", 0)
        chg = item.get("change_24h", 0)
        score = item.get("score")
        catalyst = item.get("catalyst", "")

        d_emoji = "🟢" if direction == "LONG" else ("🔴" if direction == "SHORT" else "🟡")
        chg_sign = "+" if chg >= 0 else ""
        score_str = f" | Score {score:.1f}" if score else ""
        lines.append(
            f"{d_emoji} **{sym}** ${price:,.2f} ({chg_sign}{chg:.1f}%){score_str}"
        )
        if catalyst:
            lines.append(f"   └ {catalyst}")

    lines.append(f"\n— {agent} | CooperCorp PRJ-002")
    return "\n".join(lines)

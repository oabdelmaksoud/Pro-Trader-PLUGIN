"""
Pro-Trader Setup Wizard — interactive first-time configuration.

Guides users through:
  1. OpenClaw connectivity check
  2. Trader Profile (account size, risk, goals, recovery)
  3. Broker selection + API keys (Alpaca, Tastytrade, IBKR, SnapTrade, etc.)
  3b. Optional: sync profile from live broker account data
  4. LLM provider selection + key
  5. Discord channel verification
  6. Plugin enable/disable
  7. Write .env + config files

Usage:
    pro-trader setup              # Full interactive wizard
    pro-trader setup --check      # Verify existing setup without changes
    pro-trader setup --update     # Update existing installation
    pro-trader setup --uninstall  # Remove Pro-Trader config and package
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.columns import Columns
    from rich.rule import Rule
    from rich.align import Align
    from rich.text import Text
    from rich.padding import Padding
except ImportError:
    print("Missing dependencies. Run: pip install rich")
    sys.exit(1)

console = Console()
_REPO = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _REPO / ".env"
_ENV_EXAMPLE = _REPO / ".env.example"
_USER_CONFIG_DIR = Path.home() / ".pro_trader"
_USER_CONFIG = _USER_CONFIG_DIR / "config.json"


# ── Utility helpers ──────────────────────────────────────────────────────────

def _load_env() -> dict[str, str]:
    """Parse existing .env file into a dict."""
    env = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip()
    return env


def _save_env(env: dict[str, str]) -> None:
    """Write .env preserving comments from .env.example, updating values."""
    lines: list[str] = []
    written_keys: set[str] = set()

    # Use .env.example as template if available
    template = _ENV_EXAMPLE if _ENV_EXAMPLE.exists() else _ENV_FILE
    if template and template.exists():
        for line in template.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in env:
                    lines.append(f"{key}={env[key]}")
                    written_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)

    # Append any new keys not in template
    for key, val in env.items():
        if key not in written_keys:
            lines.append(f"{key}={val}")

    _ENV_FILE.write_text("\n".join(lines) + "\n")


def _load_user_config() -> dict:
    """Load ~/.pro_trader/config.json."""
    if _USER_CONFIG.exists():
        try:
            return json.loads(_USER_CONFIG.read_text())
        except Exception:
            return {}
    return {}


def _save_user_config(cfg: dict) -> None:
    """Write ~/.pro_trader/config.json."""
    _USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _USER_CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")


def _mask(val: str) -> str:
    """Mask a secret for display: show first 4 + last 4 chars."""
    if not val or len(val) <= 8:
        return "***"
    return val[:4] + "..." + val[-4:]


def _is_placeholder(val: str) -> bool:
    """Check if value is a placeholder from .env.example."""
    placeholders = ("your_", "changeme", "xxx", "replace", "todo")
    lower = val.lower().strip()
    return any(lower.startswith(p) or lower == p for p in placeholders) or not lower


def _test_command(cmd: list[str], timeout: int = 10) -> tuple[bool, str]:
    """Run a command and return (success, output)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return False, "command not found"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, str(e)


# ── Fun UI helpers ───────────────────────────────────────────────────────

_LOGO = r"""
    ____               ______               __
   / __ \_________    /_  __/________ ______/ /__  _____
  / /_/ / ___/ __ \    / / / ___/ __ `/ __  / _ \/ ___/
 / ____/ /  / /_/ /   / / / /  / /_/ / /_/ /  __/ /
/_/   /_/   \____/   /_/ /_/   \__,_/\__,_/\___/_/
"""

_STEP_ICONS = {
    1: ("link",     "OpenClaw"),
    2: ("user",     "Trader Profile"),
    3: ("building", "Broker"),
    4: ("brain",    "AI Engine"),
    5: ("chat",     "Discord"),
    6: ("puzzle",   "Plugins"),
}

_TRADER_ARCHETYPES = {
    ("conservative", "beginner", "swing"):    ("The Steady Builder",   "Patient, disciplined, building brick by brick."),
    ("conservative", "beginner", "position"): ("The Patient Saver",    "Long-term vision, slow and steady wins the race."),
    ("conservative", "intermediate", "swing"):("The Risk Manager",     "Calculated moves, always protecting the downside."),
    ("moderate", "beginner", "swing"):        ("The Apprentice",       "Learning the ropes with balanced risk."),
    ("moderate", "intermediate", "swing"):    ("The Balanced Trader",  "Data-driven, disciplined, consistent."),
    ("moderate", "intermediate", "day_trade"):("The Precision Sniper", "Quick, focused strikes with solid risk management."),
    ("moderate", "advanced", "swing"):        ("The Tactician",        "Strategic plays with market-tested discipline."),
    ("aggressive", "intermediate", "day_trade"):("The Momentum Hunter","Riding waves, cutting losses fast, stacking gains."),
    ("aggressive", "advanced", "day_trade"):  ("The Apex Predator",    "High conviction, high frequency, maximum intensity."),
    ("aggressive", "advanced", "swing"):      ("The Big Game Hunter",  "Waiting for the perfect setup, then going big."),
}
_DEFAULT_ARCHETYPE = ("The Trader", "Forging your own path in the markets.")


def _step_header(step: int, total: int = 6) -> None:
    """Print a beautiful step header with progress indicator."""
    icon, label = _STEP_ICONS.get(step, ("?", "Unknown"))
    filled = step
    empty = total - step

    # Progress bar with blocks
    bar = "[bold green]" + "=" * (filled * 4) + "[/bold green]"
    if empty > 0:
        bar += "[dim]" + "-" * (empty * 4) + "[/dim]"

    console.print()
    console.print(
        f"  [dim]{bar}[/dim]  [bold]{step}[/bold][dim]/{total}[/dim]"
    )
    console.print(
        f"  [bold cyan]Step {step} — {label}[/bold cyan]"
    )
    console.print()


def _celebrate(message: str, style: str = "bold green") -> None:
    """Print a celebration message with flair."""
    console.print(f"\n  [{style}]{message}[/{style}]")


def _get_archetype(risk: str, exp: str, style: str) -> tuple[str, str]:
    """Get trader archetype based on profile traits."""
    key = (risk, exp, style)
    return _TRADER_ARCHETYPES.get(key, _DEFAULT_ARCHETYPE)


def _print_welcome_banner() -> None:
    """Print the awesome welcome banner."""
    console.print()
    console.print(
        Panel(
            Align.center(
                Text.from_markup(
                    f"[bold cyan]{_LOGO}[/bold cyan]\n"
                    "[bold white]Setup Wizard[/bold white]\n\n"
                    "[dim]Your AI trading co-pilot is about to come online.[/dim]\n"
                    "[dim]Let's configure everything in ~3 minutes.[/dim]\n\n"
                    "[dim italic]Press Ctrl+C at any time to cancel.[/dim italic]"
                )
            ),
            border_style="cyan",
            padding=(1, 4),
        )
    )
    console.print()


def _print_checkpoint(label: str) -> None:
    """Print a mini checkpoint / completion marker."""
    console.print(f"  [green]>>>[/green] {label}")


def _broker_card(name: str, cfg: dict, num: int) -> Panel:
    """Create a visually appealing broker card."""
    assets_map = {
        "alpaca":    "Stocks  Options  Crypto",
        "tastytrade":"Options  Futures  Stocks  Crypto",
        "ibkr":      "Stocks  Options  Futures  Forex  Crypto",
        "snaptrade": "20+ brokers via one connection",
        "tradier":   "Stocks  Options",
        "schwab":    "Stocks  Options  Futures",
        "coinbase":  "Crypto",
    }
    status_map = {
        "alpaca":    "[green]Ready[/green]",
        "tastytrade":"[green]Ready[/green]",
        "ibkr":      "[green]Ready[/green]",
        "snaptrade": "[green]Ready[/green]",
        "tradier":   "[yellow]Beta[/yellow]",
        "schwab":    "[dim]Coming Soon[/dim]",
        "coinbase":  "[dim]Coming Soon[/dim]",
    }
    assets = assets_map.get(name, "")
    status = status_map.get(name, "")

    body = (
        f"[bold]{cfg['label']}[/bold]\n"
        f"[dim]{assets}[/dim]\n"
        f"Status: {status}"
    )
    return Panel(body, title=f"[bold]{num}[/bold]", width=40, border_style="blue")


# ── Wizard Steps ─────────────────────────────────────────────────────────────

def _step_openclaw() -> dict:
    """Step 1: Check OpenClaw installation."""
    _step_header(1)

    result = {"openclaw_available": False, "openclaw_version": None}

    if not shutil.which("openclaw"):
        console.print("[yellow]openclaw CLI not found in PATH.[/yellow]")
        console.print("  Pro-Trader works without OpenClaw but Discord notifications")
        console.print("  will be disabled. Install openclaw to enable Discord alerts.")
        console.print("  [dim]pip install openclaw  # or see openclaw docs[/dim]\n")
        return result

    ok, version = _test_command(["openclaw", "--version"])
    if ok:
        result["openclaw_available"] = True
        result["openclaw_version"] = version
        console.print(f"  [green]openclaw found:[/green] {version}")
        # Warn if version is below minimum compatible (v2026.2.26)
        if "v2026" not in version and "2026" not in version:
            console.print("  [yellow]WARNING: Pro-Trader is tested with openclaw v2026.x[/yellow]")
            console.print("  [dim]message send CLI is stable across versions, but newer is better[/dim]")
    else:
        console.print(f"  [yellow]openclaw found but --version failed:[/yellow] {version}")

    # Probe the CLI subcommands Pro-Trader actually uses
    for subcmd, label in [
        (["openclaw", "message", "send", "--help"], "message send"),
        (["openclaw", "cron", "list", "--help"], "cron list"),
    ]:
        ok, out = _test_command(subcmd)
        status = "[green]available[/green]" if ok else "[yellow]not available[/yellow]"
        console.print(f"  {label} — {status}")

    return result


def _step_trader_profile(existing: dict) -> dict:
    """Step 2: Collect trader profile — account, risk, goals, recovery."""
    _step_header(2)
    console.print(
        "  [dim]This helps AI agents personalize analysis to YOUR situation.[/dim]"
    )
    console.print(
        "  [dim]Think of it as your trading DNA — the AI will adapt to match.[/dim]\n"
    )

    profile = existing.get("trader_profile", {})

    # ── Account & Capital ─────────────────────────────────────────
    console.print("  [bold]Account & Capital[/bold]")

    account_size = Prompt.ask(
        "  Current account size ($)",
        default=str(profile.get("account_size", 500)),
    )
    try:
        account_size = float(account_size)
    except ValueError:
        account_size = 500.0

    peak_val = profile.get("peak_account_value")
    peak_str = Prompt.ask(
        "  Highest account value ever ($, or 'skip')",
        default=str(peak_val) if peak_val else "skip",
    )
    peak_account_value = None
    if peak_str.lower() != "skip":
        try:
            peak_account_value = float(peak_str)
        except ValueError:
            pass

    monthly_deposit_str = Prompt.ask(
        "  Monthly deposit to this account ($, or 0)",
        default=str(profile.get("monthly_deposit", 0)),
    )
    try:
        monthly_deposit = float(monthly_deposit_str)
    except ValueError:
        monthly_deposit = 0.0

    # Auto-detect recovery situation
    losses_to_recover = 0.0
    recovery_mode = False
    if peak_account_value and peak_account_value > account_size:
        losses_to_recover = peak_account_value - account_size
        console.print(f"\n  [yellow]Detected loss: ${losses_to_recover:,.0f} "
                       f"({losses_to_recover / peak_account_value * 100:.0f}% drawdown)[/yellow]")
        recovery_mode = Confirm.ask("  Enable recovery mode?", default=True)
    else:
        recover_input = Prompt.ask(
            "  Losses to recover ($, or 0)",
            default=str(profile.get("losses_to_recover", 0)),
        )
        try:
            losses_to_recover = float(recover_input)
        except ValueError:
            losses_to_recover = 0.0
        if losses_to_recover > 0:
            recovery_mode = Confirm.ask("  Enable recovery mode?", default=True)

    # ── Risk Tolerance ────────────────────────────────────────────
    console.print("\n  [bold]Risk Tolerance[/bold]")
    console.print("    1. [green]Conservative[/green]  — Protect capital first, smaller positions")
    console.print("    2. [yellow]Moderate[/yellow]      — Balanced risk/reward (default)")
    console.print("    3. [red]Aggressive[/red]    — Higher risk for higher returns")

    risk_map = {"1": "conservative", "2": "moderate", "3": "aggressive"}
    current_risk = profile.get("risk_tolerance", "moderate")
    default_risk = {"conservative": "1", "moderate": "2", "aggressive": "3"}.get(current_risk, "2")
    risk_choice = Prompt.ask("  Risk tolerance", choices=["1", "2", "3"], default=default_risk)
    risk_tolerance = risk_map[risk_choice]

    # Risk parameters driven by tolerance
    risk_defaults = {
        "conservative": {"max_loss_per_trade": 1.0, "max_daily_loss": 2.0, "max_drawdown": 3.0},
        "moderate":     {"max_loss_per_trade": 2.0, "max_daily_loss": 3.0, "max_drawdown": 5.0},
        "aggressive":   {"max_loss_per_trade": 3.0, "max_daily_loss": 5.0, "max_drawdown": 8.0},
    }
    rd = risk_defaults[risk_tolerance]

    max_loss_trade = Prompt.ask(
        "  Max risk per trade (%)",
        default=str(profile.get("max_loss_per_trade_pct", rd["max_loss_per_trade"])),
    )
    max_daily = Prompt.ask(
        "  Max daily loss before stopping (%)",
        default=str(profile.get("max_daily_loss_pct", rd["max_daily_loss"])),
    )
    max_dd = Prompt.ask(
        "  Max portfolio drawdown before full halt (%)",
        default=str(profile.get("max_drawdown_pct", rd["max_drawdown"])),
    )

    # ── Behavioral Risk (Schwab IPQ-style) ────────────────────────
    console.print("\n  [bold]Risk Behavior[/bold]")
    console.print(
        Panel(
            "[bold]Scenario:[/bold] Your portfolio just dropped [red]20%[/red] in a month.\n"
            "What do you do?\n\n"
            "  1. [red]Sell everything[/red]       -- \"Get me out!\"\n"
            "  2. [yellow]Sell some[/yellow]             -- \"Reduce the pain\"\n"
            "  3. [green]Hold and wait[/green]          -- \"This too shall pass\"\n"
            "  4. [bold green]Buy more[/bold green]              -- \"Stocks on sale!\"",
            title="[bold] Gut Check [/bold]",
            border_style="yellow",
            width=60,
            padding=(1, 2),
        )
    )

    reaction_map = {"1": "sell_all", "2": "sell_some", "3": "hold", "4": "buy_more"}
    current_reaction = profile.get("reaction_to_loss", "hold")
    default_reaction = {"sell_all": "1", "sell_some": "2", "hold": "3", "buy_more": "4"}.get(current_reaction, "3")
    reaction_choice = Prompt.ask("  Your reaction", choices=["1", "2", "3", "4"], default=default_reaction)
    reaction_to_loss = reaction_map[reaction_choice]

    worst_loss_str = Prompt.ask(
        "  Most you'd accept losing on a single trade ($)",
        default=str(profile.get("worst_acceptable_loss") or int(account_size * 0.02)),
    )
    try:
        worst_acceptable_loss = float(worst_loss_str)
    except ValueError:
        worst_acceptable_loss = account_size * 0.02

    consec_loss_str = Prompt.ask(
        "  Pause trading after how many losses in a row?",
        default=str(profile.get("consecutive_loss_tolerance", 3)),
    )
    try:
        consecutive_loss_tolerance = int(consec_loss_str)
    except ValueError:
        consecutive_loss_tolerance = 3

    # ── Position Sizing ───────────────────────────────────────────
    console.print("\n  [bold]Position Sizing[/bold]")
    console.print("    1. Fixed percent    — Same % of account per trade (default)")
    console.print("    2. Kelly criterion  — Math-optimal sizing (more volatile)")
    console.print("    3. Volatility-based — Smaller in volatile markets")

    sizing_map = {"1": "fixed_percent", "2": "kelly", "3": "volatility"}
    current_sizing = profile.get("position_sizing_method", "fixed_percent")
    default_sizing = {"fixed_percent": "1", "kelly": "2", "volatility": "3"}.get(current_sizing, "1")
    sizing_choice = Prompt.ask("  Sizing method", choices=["1", "2", "3"], default=default_sizing)
    position_sizing_method = sizing_map[sizing_choice]

    # Position limits driven by risk tolerance
    pos_defaults = {"conservative": 10, "moderate": 15, "aggressive": 20}
    heat_defaults = {"conservative": 4.0, "moderate": 6.0, "aggressive": 10.0}

    max_pos_pct = Prompt.ask(
        "  Max position size (% of account)",
        default=str(profile.get("max_position_pct", pos_defaults[risk_tolerance])),
    )
    max_heat = Prompt.ask(
        "  Max total portfolio risk (% of account at risk across all positions)",
        default=str(profile.get("max_portfolio_heat_pct", heat_defaults[risk_tolerance])),
    )

    # ── Trading Style ─────────────────────────────────────────────
    console.print("\n  [bold]Trading Style[/bold]")
    console.print("    1. Day trade   — In and out same day")
    console.print("    2. Swing       — Hold for days (default)")
    console.print("    3. Position    — Hold for weeks/months")

    style_map = {"1": "day_trade", "2": "swing", "3": "position"}
    period_map = {"day_trade": "hours", "swing": "days", "position": "weeks"}
    current_style = profile.get("trading_style", "swing")
    default_style = {"day_trade": "1", "swing": "2", "position": "3"}.get(current_style, "2")
    style_choice = Prompt.ask("  Trading style", choices=["1", "2", "3"], default=default_style)
    trading_style = style_map[style_choice]

    # Market hours availability
    console.print("\n  When can you monitor the market?")
    console.print("    1. Full day    — Available during market hours")
    console.print("    2. Morning     — Only first few hours")
    console.print("    3. Evening     — Review after close")
    console.print("    4. Can't watch — Fully automated/alerts only")

    hours_map = {"1": "full_day", "2": "morning", "3": "evening", "4": "cannot_monitor"}
    current_hours = profile.get("market_hours_available", "full_day")
    default_hours = {"full_day": "1", "morning": "2", "evening": "3", "cannot_monitor": "4"}.get(current_hours, "1")
    hours_choice = Prompt.ask("  Availability", choices=["1", "2", "3", "4"], default=default_hours)
    market_hours = hours_map[hours_choice]

    if market_hours == "cannot_monitor" and trading_style == "day_trade":
        console.print("  [yellow]Day trading requires market monitoring — switching to swing.[/yellow]")
        trading_style = "swing"

    # Asset preferences
    console.print("\n  [bold]Preferred Assets[/bold] (comma-separated)")
    console.print("    Options: equities, futures, crypto, fx")
    current_assets = profile.get("preferred_assets", ["equities"])
    assets_str = Prompt.ask("  Assets", default=", ".join(current_assets))
    preferred_assets = [a.strip().lower() for a in assets_str.split(",") if a.strip()]

    # ── Experience & Goals ────────────────────────────────────────
    console.print("\n  [bold]Experience & Goals[/bold]")
    console.print("    Experience: 1. Beginner  2. Intermediate  3. Advanced")

    exp_map = {"1": "beginner", "2": "intermediate", "3": "advanced"}
    current_exp = profile.get("experience_level", "intermediate")
    default_exp = {"beginner": "1", "intermediate": "2", "advanced": "3"}.get(current_exp, "2")
    exp_choice = Prompt.ask("  Experience level", choices=["1", "2", "3"], default=default_exp)

    console.print("    Goal: 1. Growth  2. Income  3. Recovery  4. Preservation")
    goal_map = {"1": "growth", "2": "income", "3": "recovery", "4": "preservation"}
    current_goal = profile.get("trading_goal", "recovery" if recovery_mode else "growth")
    default_goal = {"growth": "1", "income": "2", "recovery": "3", "preservation": "4"}.get(current_goal, "1")
    goal_choice = Prompt.ask("  Trading goal", choices=["1", "2", "3", "4"], default=default_goal)

    # ── Autonomy ──────────────────────────────────────────────────
    console.print("\n  [bold]Autonomy Level[/bold]")
    console.print("  [dim]How much freedom should the AI have?[/dim]\n")
    console.print(
        "    1. [dim]Notify only[/dim]    -- AI watches, you drive"
    )
    console.print(
        "    2. [bold]Suggest[/bold]        -- AI co-pilot: proposes trades, you approve"
    )
    console.print(
        "    3. [yellow]Semi-auto[/yellow]      -- AI auto-trades small positions, asks for big ones"
    )
    console.print(
        "    4. [red]Full auto[/red]      -- AI takes the wheel (risk limits still enforced)"
    )

    auto_map = {"1": "notify_only", "2": "suggest", "3": "semi_auto", "4": "full_auto"}
    current_auto = profile.get("autonomy_level", "suggest")
    default_auto = {"notify_only": "1", "suggest": "2", "semi_auto": "3", "full_auto": "4"}.get(current_auto, "2")
    auto_choice = Prompt.ask("  Autonomy", choices=["1", "2", "3", "4"], default=default_auto)
    autonomy_level = auto_map[auto_choice]

    if autonomy_level == "full_auto":
        console.print("  [red]Full auto: AI will execute trades without asking. "
                       "Risk limits still apply.[/red]")
        if not Confirm.ask("  Confirm full auto?", default=False):
            autonomy_level = "suggest"
            console.print("  [green]Switched to suggest mode.[/green]")

    # ── Recovery Plan ─────────────────────────────────────────────
    recovery_timeline_weeks = None
    recovery_strategy = "moderate"
    loss_cause = None
    cooldown_hours = 24

    if recovery_mode:
        target = account_size + losses_to_recover
        pct_down = (losses_to_recover / target * 100) if target > 0 else 0
        console.print()
        console.print(
            Panel(
                f"[bold]Current:[/bold] ${account_size:,.0f}  -->  "
                f"[bold green]Target:[/bold green] ${target:,.0f}  "
                f"[dim]({pct_down:.0f}% to recover)[/dim]\n\n"
                "[dim]Every successful trader has been here. "
                "The difference is having a plan.[/dim]",
                title="[bold yellow] Recovery Mode [/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            )
        )

        if monthly_deposit > 0:
            months_deposits_only = losses_to_recover / monthly_deposit
            console.print(f"  [dim]At ${monthly_deposit:,.0f}/mo deposits alone: "
                           f"~{months_deposits_only:.0f} months to recover[/dim]")

        # What caused the losses?
        console.print("\n  What caused the losses?")
        console.print("    1. Market crash / correction")
        console.print("    2. Bad stock picks")
        console.print("    3. Over-leveraged positions")
        console.print("    4. Emotional / revenge trading")
        console.print("    5. Not sure / multiple reasons")

        cause_map = {
            "1": "market_crash", "2": "bad_picks", "3": "overleveraged",
            "4": "emotional_trading", "5": "unknown",
        }
        current_cause = profile.get("loss_cause", "unknown")
        default_cause = {v: k for k, v in cause_map.items()}.get(current_cause, "5")
        cause_choice = Prompt.ask("  Loss cause", choices=["1", "2", "3", "4", "5"], default=default_cause)
        loss_cause = cause_map[cause_choice]

        # Tailored advice based on cause
        cause_advice = {
            "emotional_trading": "AI will enforce strict automation — no manual overrides recommended.",
            "overleveraged": "AI will cap margin usage and reduce position sizes.",
            "bad_picks": "AI will raise score threshold — only highest-conviction trades.",
            "market_crash": "Strategy stays the same, adding macro monitoring weight.",
        }
        if loss_cause in cause_advice:
            console.print(f"  [cyan]{cause_advice[loss_cause]}[/cyan]")

        timeline = Prompt.ask(
            "  Recovery timeline (weeks, or 'no_rush')",
            default=str(profile.get("recovery_timeline_weeks", "no_rush")),
        )
        if timeline.lower() != "no_rush":
            try:
                recovery_timeline_weeks = int(timeline)
            except ValueError:
                pass

        console.print("\n  [bold]Recovery Strategy:[/bold]")
        console.print(
            "    1. [green]Conservative rebuild[/green]  -- Tortoise mode: slow, safe, no shortcuts"
        )
        console.print(
            "    2. [yellow]Moderate recovery[/yellow]    -- Balanced: slightly larger bets, strict rules"
        )
        console.print(
            "    3. [red]Aggressive recovery[/red]   -- Hare mode: max risk within safety limits"
        )

        rec_map = {"1": "conservative_rebuild", "2": "moderate", "3": "aggressive"}
        current_rec = profile.get("recovery_strategy", "moderate")
        default_rec = {"conservative_rebuild": "1", "moderate": "2", "aggressive": "3"}.get(current_rec, "2")
        rec_choice = Prompt.ask("  Recovery strategy", choices=["1", "2", "3"], default=default_rec)
        recovery_strategy = rec_map[rec_choice]

        cooldown_str = Prompt.ask(
            "  Cooldown hours after hitting loss limit",
            default=str(profile.get("cooldown_hours", 24)),
        )
        try:
            cooldown_hours = int(cooldown_str)
        except ValueError:
            cooldown_hours = 24

        if recovery_timeline_weeks and losses_to_recover > 0:
            weekly_target = losses_to_recover / recovery_timeline_weeks
            weekly_pct = (weekly_target / account_size) * 100
            console.print(
                f"\n  Weekly target: [bold]${weekly_target:,.0f}/wk[/bold] "
                f"({weekly_pct:.1f}% of account)"
            )
            if weekly_pct > 10:
                console.print(
                    "  [red]That's a sprint, not a jog. "
                    "AI will keep you from blowing up.[/red]"
                )
            elif weekly_pct > 5:
                console.print(
                    "  [yellow]Ambitious but doable. "
                    "Discipline is your edge here.[/yellow]"
                )
            else:
                console.print(
                    "  [green]Steady pace. "
                    "Consistency will get you there.[/green]"
                )

    # ── Build profile dict ────────────────────────────────────────
    result = {
        # Account & Capital
        "account_size": account_size,
        "peak_account_value": peak_account_value,
        "losses_to_recover": losses_to_recover,
        "recovery_mode": recovery_mode,
        "monthly_deposit": monthly_deposit,
        # Risk Tolerance
        "risk_tolerance": risk_tolerance,
        "max_loss_per_trade_pct": float(max_loss_trade),
        "max_daily_loss_pct": float(max_daily),
        "max_drawdown_pct": float(max_dd),
        # Behavioral Risk
        "reaction_to_loss": reaction_to_loss,
        "worst_acceptable_loss": worst_acceptable_loss,
        "consecutive_loss_tolerance": consecutive_loss_tolerance,
        # Position Sizing
        "position_sizing_method": position_sizing_method,
        "max_position_pct": float(max_pos_pct),
        "max_portfolio_heat_pct": float(max_heat),
        # Trading Style
        "trading_style": trading_style,
        "holding_period": period_map.get(trading_style, "days"),
        "preferred_assets": preferred_assets,
        "market_hours_available": market_hours,
        # Experience & Goals
        "experience_level": exp_map[exp_choice],
        "trading_goal": goal_map[goal_choice],
        # Autonomy
        "autonomy_level": autonomy_level,
        # Recovery Plan
        "recovery_timeline_weeks": recovery_timeline_weeks,
        "recovery_strategy": recovery_strategy,
        "loss_cause": loss_cause,
        "cooldown_hours": cooldown_hours,
    }

    # ── Archetype Reveal ──────────────────────────────────────────
    archetype_name, archetype_desc = _get_archetype(
        risk_tolerance, exp_map[exp_choice], trading_style,
    )

    console.print()
    console.print(Rule("[bold cyan] Your Trader Profile [/bold cyan]"))
    console.print()

    # Left column: stats
    stats_lines = [
        f"[bold]Account:[/bold]        ${account_size:,.0f}",
    ]
    if monthly_deposit > 0:
        stats_lines.append(f"[bold]Monthly add:[/bold]    ${monthly_deposit:,.0f}")
    if recovery_mode:
        stats_lines.append(
            f"[bold]Recovery:[/bold]       ${losses_to_recover:,.0f} "
            f"-> ${account_size + losses_to_recover:,.0f}"
        )
    stats_lines += [
        f"[bold]Risk:[/bold]           {risk_tolerance}",
        f"[bold]Style:[/bold]          {trading_style} ({period_map.get(trading_style, 'days')})",
        f"[bold]Assets:[/bold]         {', '.join(preferred_assets)}",
        f"[bold]Experience:[/bold]     {exp_map[exp_choice]}",
        f"[bold]Autonomy:[/bold]       {autonomy_level}",
    ]
    stats_text = "\n".join(stats_lines)

    # Right column: archetype card
    risk_colors = {
        "conservative": "green",
        "moderate": "yellow",
        "aggressive": "red",
    }
    risk_color = risk_colors.get(risk_tolerance, "white")

    archetype_card = Panel(
        Align.center(
            Text.from_markup(
                f"\n[bold {risk_color}]{archetype_name}[/bold {risk_color}]\n\n"
                f"[italic]{archetype_desc}[/italic]\n\n"
                f"[dim]{risk_tolerance.upper()} | "
                f"{exp_map[exp_choice].upper()} | "
                f"{trading_style.upper()}[/dim]\n"
            )
        ),
        title="[bold]Your Archetype[/bold]",
        border_style=risk_color,
        width=44,
    )

    console.print(
        Columns(
            [
                Padding(Text.from_markup(stats_text), (1, 2)),
                archetype_card,
            ],
            padding=(0, 2),
        )
    )

    _celebrate("Profile locked in. The AI knows who you are now.")

    return result


_BROKER_CONFIGS = {
    "alpaca": {
        "label": "Alpaca (stocks, options, crypto)",
        "env_keys": {
            "ALPACA_API_KEY": ("Alpaca API key", False),
            "ALPACA_SECRET_KEY": ("Alpaca secret key", True),
        },
        "has_paper": True,
        "test_cmd": (
            "import alpaca_trade_api as t; "
            "a=t.REST(); print(a.get_account().status)"
        ),
        "test_env_map": {
            "ALPACA_API_KEY": "APCA_API_KEY_ID",
            "ALPACA_SECRET_KEY": "APCA_API_SECRET_KEY",
            "ALPACA_BASE_URL": "APCA_API_BASE_URL",
        },
    },
    "tastytrade": {
        "label": "Tastytrade (options, futures, stocks, crypto)",
        "env_keys": {
            "TASTYTRADE_USERNAME": ("Tastytrade username", False),
            "TASTYTRADE_PASSWORD": ("Tastytrade password", True),
        },
        "has_paper": False,
        "test_cmd": (
            "from tastytrade import Session; "
            "import os; "
            "s=Session(os.environ['TASTYTRADE_USERNAME'], "
            "os.environ['TASTYTRADE_PASSWORD']); print('ok')"
        ),
        "test_env_map": {},
    },
    "ibkr": {
        "label": "Interactive Brokers (requires TWS/Gateway running)",
        "env_keys": {
            "IBKR_HOST": ("TWS/Gateway host", False),
            "IBKR_PORT": ("TWS/Gateway port", False),
            "IBKR_CLIENT_ID": ("Client ID", False),
        },
        "has_paper": False,
        "test_cmd": None,
        "test_env_map": {},
    },
    "snaptrade": {
        "label": "SnapTrade (20+ brokers: Robinhood, Fidelity, Schwab...)",
        "env_keys": {
            "SNAPTRADE_CLIENT_ID": ("SnapTrade client ID", False),
            "SNAPTRADE_CONSUMER_KEY": ("SnapTrade consumer key", True),
        },
        "has_paper": False,
        "test_cmd": None,
        "test_env_map": {},
    },
    "tradier": {
        "label": "Tradier (stocks, options)",
        "env_keys": {
            "TRADIER_ACCESS_TOKEN": ("Tradier access token", True),
            "TRADIER_ACCOUNT_ID": ("Tradier account ID", False),
        },
        "has_paper": False,
        "test_cmd": None,
        "test_env_map": {},
    },
    "schwab": {
        "label": "Charles Schwab (stub — OAuth pending)",
        "env_keys": {
            "SCHWAB_APP_KEY": ("Schwab app key", False),
            "SCHWAB_APP_SECRET": ("Schwab app secret", True),
        },
        "has_paper": False,
        "test_cmd": None,
        "test_env_map": {},
    },
    "coinbase": {
        "label": "Coinbase (crypto — stub)",
        "env_keys": {
            "COINBASE_API_KEY": ("Coinbase API key", False),
            "COINBASE_API_SECRET": ("Coinbase API secret", True),
        },
        "has_paper": False,
        "test_cmd": None,
        "test_env_map": {},
    },
}


def _configure_single_broker(
    broker_name: str, env: dict[str, str],
) -> bool:
    """Collect credentials for a single broker. Returns True if configured."""
    cfg = _BROKER_CONFIGS.get(broker_name)
    if not cfg:
        return False

    console.print(f"\n  [bold]{cfg['label']}[/bold]")

    for env_key, (prompt_text, is_secret) in cfg["env_keys"].items():
        current = env.get(env_key, "")
        has_val = current and not _is_placeholder(current)
        if has_val:
            console.print(f"    {prompt_text}: {_mask(current)}")
        val = Prompt.ask(
            f"    {prompt_text}",
            default=current if has_val else "",
            password=is_secret,
        )
        env[env_key] = val

    # Paper trading toggle for Alpaca
    if cfg["has_paper"]:
        paper = Confirm.ask("    Use paper trading?", default=True)
        base_url = (
            "https://paper-api.alpaca.markets" if paper
            else "https://api.alpaca.markets"
        )
        if not paper:
            console.print(
                "    [bold red]WARNING: Live trading. "
                "Real money at risk.[/bold red]"
            )
            if not Confirm.ask("    Confirm live trading?", default=False):
                base_url = "https://paper-api.alpaca.markets"
                console.print(
                    "    [green]Switched back to paper trading.[/green]"
                )
        env["ALPACA_BASE_URL"] = base_url

    # Test connection if available
    test_cmd = cfg.get("test_cmd")
    if test_cmd:
        has_creds = all(
            env.get(k, "") and not _is_placeholder(env.get(k, ""))
            for k in cfg["env_keys"]
        )
        if has_creds:
            console.print(
                f"    Testing {broker_name} connection...", end=" ",
            )
            try:
                test_env = os.environ.copy()
                # Map env vars for the test subprocess
                for src, dst in cfg.get("test_env_map", {}).items():
                    test_env[dst] = env.get(src, "")
                for k in cfg["env_keys"]:
                    test_env[k] = env.get(k, "")
                r = subprocess.run(
                    [sys.executable, "-c", test_cmd],
                    capture_output=True, text=True, timeout=15,
                    env=test_env,
                )
                if r.returncode == 0 and r.stdout.strip():
                    console.print(
                        f"[green]{r.stdout.strip()}[/green]"
                    )
                else:
                    err = r.stderr.strip()[:80]
                    console.print(
                        f"[yellow]could not verify ({err})[/yellow]"
                    )
            except Exception:
                console.print(
                    f"[yellow]skipped ({broker_name} SDK "
                    f"not installed)[/yellow]"
                )

    return True


def _step_broker(
    env: dict[str, str],
) -> tuple[dict[str, str], list[str], str]:
    """Step 3: Configure broker(s) — multi-broker selection."""
    _step_header(3)

    console.print(
        "  [dim]Connect your brokerage to enable live trading, "
        "portfolio sync, and real-time data.[/dim]\n"
    )

    broker_names = list(_BROKER_CONFIGS.keys())

    # Show broker cards in a grid
    cards = []
    for i, name in enumerate(broker_names, 1):
        cfg = _BROKER_CONFIGS[name]
        cards.append(_broker_card(name, cfg, i))

    # Print cards in rows of 2
    for row_start in range(0, len(cards), 2):
        row_cards = cards[row_start:row_start + 2]
        console.print(Columns(row_cards, padding=(0, 1)))

    console.print(f"\n    [dim]s. Skip (no broker — you can add one later)[/dim]")

    choice = Prompt.ask(
        "  Select brokers (comma-separated, e.g. '1,4')", default="1",
    )

    if choice.strip().lower() == "s":
        return env, [], ""

    selected = []
    for part in choice.split(","):
        part = part.strip()
        try:
            idx = int(part) - 1
            if 0 <= idx < len(broker_names):
                selected.append(broker_names[idx])
        except ValueError:
            # Try as broker name
            if part in broker_names:
                selected.append(part)

    if not selected:
        console.print("  [yellow]No valid broker selected — skipping[/yellow]")
        return env, [], ""

    # Configure each selected broker
    for broker_name in selected:
        _configure_single_broker(broker_name, env)

    # Select primary broker
    primary = selected[0]
    if len(selected) > 1:
        console.print(f"\n  Selected brokers: {', '.join(selected)}")
        console.print("  Which broker should handle trade execution?")
        for i, name in enumerate(selected, 1):
            console.print(f"    {i}. {name}")
        p_choice = Prompt.ask("  Primary broker", default="1")
        try:
            p_idx = int(p_choice) - 1
            if 0 <= p_idx < len(selected):
                primary = selected[p_idx]
        except ValueError:
            pass

    _celebrate(f"Primary broker: {primary} -- connected and ready.")
    return env, selected, primary


def _try_broker_sync(
    env: dict[str, str],
    brokers: list[str],
    trader_profile: dict,
) -> dict:
    """After broker setup, offer to sync profile from live account data."""
    if not brokers:
        return trader_profile

    if not Confirm.ask(
        "\n  Sync trader profile from live broker account data?",
        default=True,
    ):
        return trader_profile

    for broker_name in brokers:
        console.print(
            f"  Fetching account data from {broker_name}...", end=" ",
        )
        try:
            summary = _fetch_broker_summary(broker_name, env)
            if summary and summary.get("equity", 0) > 0:
                equity = summary["equity"]
                console.print(
                    f"[green]${equity:,.2f} equity[/green]"
                )
                trader_profile["account_size"] = equity
                trader_profile["peak_account_value"] = max(
                    equity,
                    trader_profile.get("peak_account_value") or 0,
                )
                if summary.get("pattern_day_trader"):
                    trader_profile["trading_style"] = "day_trade"
                    console.print(
                        "    [dim]Pattern day trader detected[/dim]"
                    )
                if summary.get("position_symbols"):
                    symbols = summary["position_symbols"]
                    console.print(
                        f"    Open positions: "
                        f"{', '.join(symbols[:10])}"
                    )
                console.print(
                    f"    Updated account_size → ${equity:,.2f}"
                )
                break  # Use first successful broker
            else:
                console.print("[yellow]no equity data[/yellow]")
        except Exception as e:
            console.print(f"[yellow]failed: {e}[/yellow]")

    return trader_profile


def _fetch_broker_summary(
    broker_name: str, env: dict[str, str],
) -> dict | None:
    """Instantiate a broker plugin and fetch account summary."""
    # Inject env vars for the broker
    old_env = {}
    cfg = _BROKER_CONFIGS.get(broker_name, {})
    for key in cfg.get("env_keys", {}):
        old_env[key] = os.environ.get(key)
        if env.get(key):
            os.environ[key] = env[key]
    # Also set Alpaca-specific env mapping
    if broker_name == "alpaca":
        for src, dst in cfg.get("test_env_map", {}).items():
            old_env[dst] = os.environ.get(dst)
            os.environ[dst] = env.get(src, "")
        old_env["ALPACA_BASE_URL"] = os.environ.get("ALPACA_BASE_URL")
        if env.get("ALPACA_BASE_URL"):
            os.environ["ALPACA_BASE_URL"] = env["ALPACA_BASE_URL"]

    try:
        from pro_trader.models.position import AccountSummary
        plugin = _get_broker_plugin_instance(broker_name)
        if not plugin:
            return None
        plugin.startup()
        if not plugin.enabled:
            return None
        summary = plugin.get_account_summary()
        if not isinstance(summary, AccountSummary):
            return None
        return {
            "equity": summary.equity,
            "cash": summary.cash,
            "buying_power": summary.buying_power,
            "today_pnl": summary.today_pnl,
            "pattern_day_trader": summary.pattern_day_trader,
            "open_positions": summary.open_positions,
            "position_symbols": summary.position_symbols,
        }
    except Exception:
        return None
    finally:
        # Restore original env
        for key, val in old_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def _get_broker_plugin_instance(broker_name: str):
    """Import and instantiate a broker plugin by name."""
    broker_modules = {
        "alpaca": (
            "pro_trader.plugins.brokers.alpaca_broker",
            "AlpacaBrokerPlugin",
        ),
        "tastytrade": (
            "pro_trader.plugins.brokers.tastytrade_broker",
            "TastytradeBrokerPlugin",
        ),
        "ibkr": (
            "pro_trader.plugins.brokers.ibkr_broker",
            "IBKRBrokerPlugin",
        ),
        "snaptrade": (
            "pro_trader.plugins.brokers.snaptrade_broker",
            "SnapTradeBrokerPlugin",
        ),
        "tradier": (
            "pro_trader.plugins.brokers.tradier_broker",
            "TradierBrokerPlugin",
        ),
        "schwab": (
            "pro_trader.plugins.brokers.schwab_broker",
            "SchwabBrokerPlugin",
        ),
        "coinbase": (
            "pro_trader.plugins.brokers.coinbase_broker",
            "CoinbaseBrokerPlugin",
        ),
    }
    entry = broker_modules.get(broker_name)
    if not entry:
        return None
    import importlib
    mod = importlib.import_module(entry[0])
    cls = getattr(mod, entry[1])
    return cls()


def _step_llm(env: dict[str, str]) -> dict[str, str]:
    """Step 4: Configure LLM provider."""
    _step_header(4)

    console.print(
        "  [dim]Choose the AI brain that powers your analysis agents.[/dim]\n"
    )

    providers = {
        "1": ("anthropic", "ANTHROPIC_API_KEY", "Anthropic (Claude)"),
        "2": ("openai", "OPENAI_API_KEY", "OpenAI (GPT)"),
        "3": ("google", "GOOGLE_API_KEY", "Google (Gemini)"),
    }

    provider_cards = []
    for num, (_, _, label) in providers.items():
        marker = " [green](recommended)[/green]" if num == "1" else ""
        provider_cards.append(
            Panel(
                f"[bold]{label}[/bold]{marker}",
                title=f"[bold]{num}[/bold]",
                width=30,
                border_style="blue" if num == "1" else "dim",
            )
        )
    console.print(Columns(provider_cards, padding=(0, 1)))

    choice = Prompt.ask("  Select provider", choices=["1", "2", "3"], default="1")
    provider, env_key, label = providers[choice]

    current_val = env.get(env_key, "")
    has_val = current_val and not _is_placeholder(current_val)

    if has_val:
        console.print(f"  Existing key: {_mask(current_val)}")
        if not Confirm.ask("  Update key?", default=False):
            env["_llm_provider"] = provider
            return env

    api_key = Prompt.ask(f"  {label} API key", default=current_val if has_val else "", password=True)
    env[env_key] = api_key
    env["_llm_provider"] = provider

    return env


def _step_discord(env: dict[str, str], openclaw_info: dict) -> dict[str, str]:
    """Step 5: Verify Discord channels."""
    _step_header(5)

    if not openclaw_info.get("openclaw_available"):
        console.print("  [dim]Skipped — openclaw not available.[/dim]")
        console.print("  Discord notifications will be disabled.")
        return env

    from pro_trader.services.openclaw import CHANNELS

    table = Table(title="Discord Channels", show_lines=False)
    table.add_column("Name", style="bold")
    table.add_column("Channel ID")
    for name, cid in CHANNELS.items():
        table.add_row(name, cid)
    console.print(table)

    if Confirm.ask("\n  Send a test message to war_room?", default=False):
        from pro_trader.services.openclaw import send_discord
        ok = send_discord("war_room", "Pro-Trader setup wizard — test message")
        if ok:
            console.print("  [green]Message sent successfully![/green]")
        else:
            console.print("  [yellow]Failed to send. Check openclaw config.[/yellow]")

    return env


def _step_plugins() -> dict:
    """Step 6: Review and toggle plugins."""
    _step_header(6)

    console.print("  [dim]These are the modules powering your trading system.[/dim]\n")

    plugin_cfg: dict = {}

    try:
        from pro_trader import ProTrader
        trader = ProTrader()
        all_plugins = trader.plugins.get_all_plugins()

        table = Table(title="Discovered Plugins")
        table.add_column("#", style="dim")
        table.add_column("Category", style="bold")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Description")

        flat: list[tuple[str, object]] = []
        for category, plugins in all_plugins.items():
            for p in plugins:
                flat.append((category, p))

        for i, (cat, p) in enumerate(flat, 1):
            status = "[green]enabled[/green]" if p.enabled else "[red]disabled[/red]"
            table.add_row(str(i), cat, p.name, status, p.description or "")

        console.print(table)

        if Confirm.ask("\n  Toggle any plugins?", default=False):
            while True:
                name = Prompt.ask(
                    "  Plugin name to toggle (empty to finish)",
                    default="",
                )
                if not name:
                    break
                found = False
                for cat, p in flat:
                    if p.name.lower() == name.lower():
                        p.enabled = not p.enabled
                        state = "enabled" if p.enabled else "disabled"
                        console.print(f"  [cyan]{p.name}[/cyan] → {state}")
                        plugin_cfg[p.name] = {"enabled": p.enabled}
                        found = True
                        break
                if not found:
                    console.print(f"  [red]Plugin '{name}' not found[/red]")

    except Exception as e:
        console.print(f"  [yellow]Could not load plugins: {e}[/yellow]")
        console.print("  [dim]You can configure plugins later with: pro-trader plugin list[/dim]")

    return plugin_cfg


# ── Check mode ───────────────────────────────────────────────────────────────

def run_check() -> None:
    """Non-interactive: verify existing setup and report status."""
    console.print(Panel("[bold]Pro-Trader Setup Check[/bold]", style="cyan"))

    env = _load_env()
    results: list[tuple[str, str, str]] = []  # (component, status, detail)

    # OpenClaw
    if shutil.which("openclaw"):
        ok, ver = _test_command(["openclaw", "--version"])
        results.append(("OpenClaw", "[green]installed[/green]", ver if ok else "version check failed"))
    else:
        results.append(("OpenClaw", "[yellow]not found[/yellow]", "Discord disabled"))

    # Alpaca
    key = env.get("ALPACA_API_KEY", "")
    if key and not _is_placeholder(key):
        url = env.get("ALPACA_BASE_URL", "paper")
        mode = "paper" if "paper" in url else "[red]LIVE[/red]"
        results.append(("Alpaca", "[green]configured[/green]", f"key={_mask(key)}, mode={mode}"))
    else:
        results.append(("Alpaca", "[red]not configured[/red]", "set ALPACA_API_KEY in .env"))

    # LLM
    for provider, env_key in [("Anthropic", "ANTHROPIC_API_KEY"), ("OpenAI", "OPENAI_API_KEY"), ("Google", "GOOGLE_API_KEY")]:
        val = env.get(env_key, "")
        if val and not _is_placeholder(val):
            results.append((provider, "[green]configured[/green]", _mask(val)))

    if not any(r[0] in ("Anthropic", "OpenAI", "Google") for r in results if "configured" in r[1]):
        results.append(("LLM Provider", "[red]none configured[/red]", "set an API key in .env"))

    # .env file
    if _ENV_FILE.exists():
        results.append((".env file", "[green]exists[/green]", str(_ENV_FILE)))
    else:
        results.append((".env file", "[red]missing[/red]", "run: pro-trader setup"))

    # User config
    if _USER_CONFIG.exists():
        results.append(("User config", "[green]exists[/green]", str(_USER_CONFIG)))
    else:
        results.append(("User config", "[dim]not created[/dim]", "optional"))

    # Plugins
    try:
        from pro_trader import ProTrader
        trader = ProTrader()
        h = trader.health()
        total = sum(len(v) for v in h.values())
        ok_count = sum(
            1 for plugins in h.values()
            for info in plugins.values()
            if info.get("status") == "ok"
        )
        results.append(("Plugins", f"[green]{ok_count}/{total} healthy[/green]", ""))
    except Exception as e:
        results.append(("Plugins", "[yellow]load error[/yellow]", str(e)[:60]))

    table = Table(title="Setup Status", show_lines=False)
    table.add_column("Component", style="bold")
    table.add_column("Status")
    table.add_column("Detail", style="dim")
    for component, status, detail in results:
        table.add_row(component, status, detail)

    console.print(table)


# ── Main wizard ──────────────────────────────────────────────────────────────

def run_wizard() -> None:
    """Run the full interactive setup wizard."""
    _print_welcome_banner()

    env = _load_env()
    user_cfg = _load_user_config()

    # Step 1: OpenClaw
    openclaw_info = _step_openclaw()

    # Step 2: Trader Profile
    trader_profile = _step_trader_profile(user_cfg)

    # Step 3: Broker (multi-broker selection)
    env, selected_brokers, primary_broker = _step_broker(env)

    # Step 3b: Sync profile from live broker data
    if selected_brokers:
        trader_profile = _try_broker_sync(env, selected_brokers, trader_profile)

    # Step 4: LLM
    env = _step_llm(env)

    # Step 5: Discord
    env = _step_discord(env, openclaw_info)

    # Step 6: Plugins
    plugin_cfg = _step_plugins()

    # ── Summary & Write ──────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold cyan] Final Review [/bold cyan]"))
    console.print()

    llm_provider = env.pop("_llm_provider", "anthropic")

    alpaca_url = env.get("ALPACA_BASE_URL", "")
    broker_display = primary_broker or "none"
    if primary_broker == "alpaca":
        broker_display += " (paper)" if "paper" in alpaca_url else " (LIVE)"
    if len(selected_brokers) > 1:
        broker_display += f" + {len(selected_brokers) - 1} more"

    # Build the archetype info
    archetype_name, archetype_desc = _get_archetype(
        trader_profile.get("risk_tolerance", "moderate"),
        trader_profile.get("experience_level", "intermediate"),
        trader_profile.get("trading_style", "swing"),
    )

    # Left: config summary table
    summary = Table(show_header=False, border_style="dim", padding=(0, 1))
    summary.add_column("Key", style="bold", min_width=16)
    summary.add_column("Value")
    summary.add_row("Account", f"${trader_profile.get('account_size', 0):,.0f}")
    summary.add_row("Risk", trader_profile.get("risk_tolerance", "moderate"))
    if trader_profile.get("recovery_mode"):
        summary.add_row(
            "Recovery",
            f"${trader_profile.get('losses_to_recover', 0):,.0f}"
        )
    summary.add_row("Broker", broker_display)
    summary.add_row("AI Engine", llm_provider)
    summary.add_row(
        "Discord",
        "[green]connected[/green]"
        if openclaw_info.get("openclaw_available")
        else "[dim]offline[/dim]",
    )
    summary.add_row("Plugins", str(len(plugin_cfg)) if plugin_cfg else "defaults")
    summary.add_row(".env", str(_ENV_FILE))
    summary.add_row("Config", str(_USER_CONFIG))

    # Right: archetype + readiness gauge
    risk_color = {
        "conservative": "green",
        "moderate": "yellow",
        "aggressive": "red",
    }.get(trader_profile.get("risk_tolerance", "moderate"), "white")

    systems_ready = sum([
        bool(primary_broker),
        bool(llm_provider),
        openclaw_info.get("openclaw_available", False),
        True,  # plugins always present
    ])
    gauge = (
        "[green]=====[/green]" if systems_ready >= 4
        else "[green]====[/green][dim]=[/dim]" if systems_ready == 3
        else "[yellow]===[/yellow][dim]==[/dim]" if systems_ready == 2
        else "[red]==[/red][dim]===[/dim]"
    )

    right_panel = Panel(
        Align.center(
            Text.from_markup(
                f"\n[bold {risk_color}]{archetype_name}[/bold {risk_color}]\n"
                f"[italic]{archetype_desc}[/italic]\n\n"
                f"Systems: {gauge} {systems_ready}/4\n"
            )
        ),
        title="[bold]Battle Station[/bold]",
        border_style=risk_color,
        width=40,
    )

    console.print(Columns([summary, right_panel], padding=(0, 2)))

    if not Confirm.ask("\n  Write configuration files?", default=True):
        console.print("[yellow]Cancelled — no files written.[/yellow]")
        return

    # Write .env
    _save_env(env)
    console.print(f"  [green]Wrote {_ENV_FILE}[/green]")

    # Write user config
    user_cfg["llm_provider"] = llm_provider
    user_cfg["trader_profile"] = trader_profile
    user_cfg["account_value"] = trader_profile.get("account_size", 500)
    if primary_broker:
        user_cfg["primary_broker"] = primary_broker
    if selected_brokers:
        user_cfg.setdefault("plugins", {})["broker"] = selected_brokers
    if plugin_cfg:
        user_cfg.setdefault("plugin_config", {}).update(plugin_cfg)
    _save_user_config(user_cfg)
    console.print(f"  [green]Wrote {_USER_CONFIG}[/green]")

    # Final message
    console.print()
    console.print(
        Panel(
            Align.center(
                Text.from_markup(
                    "[bold green]Setup complete! Your trading co-pilot is online.[/bold green]\n\n"
                    f"Archetype: [bold]{archetype_name}[/bold]\n\n"
                    "[bold]What's next?[/bold]\n\n"
                    "  [cyan]pro-trader health[/cyan]         verify all systems\n"
                    "  [cyan]pro-trader analyze NVDA[/cyan]   run your first analysis\n"
                    "  [cyan]pro-trader sync[/cyan]           pull live account data\n"
                    "  [cyan]pro-trader broker list[/cyan]    see connected brokers\n"
                    "  [cyan]pro-trader scan[/cyan]           scan your watchlist\n\n"
                    "[dim]May your entries be precise and your exits be timely.[/dim]"
                )
            ),
            border_style="green",
            padding=(1, 4),
            title="[bold green] All Systems Go [/bold green]",
        )
    )


# ── Update mode ──────────────────────────────────────────────────────────────

def run_update() -> None:
    """Update Pro-Trader installation and re-validate config."""

    # ── Helper: print a styled update step header ────────────────────────────
    def _update_step(step: int, total: int, label: str) -> None:
        filled = step
        empty = total - step
        bar = "[bold cyan]" + "\u2588" * (filled * 3) + "[/bold cyan]"
        if empty > 0:
            bar += "[dim]\u2591" * (empty * 3) + "[/dim]"
        console.print()
        console.print(Rule(style="dim cyan"))
        console.print(
            f"  {bar}  [bold white]{step}[/bold white][dim]/{total}[/dim]"
        )
        console.print(
            f"  [bold cyan]\u25b6 {label}[/bold cyan]"
        )
        console.print()

    # ── Update banner ───────────────────────────────────────────────────────
    console.print()
    console.print(
        Panel(
            Align.center(
                Text.from_markup(
                    f"[bold cyan]{_LOGO}[/bold cyan]\n"
                    "[bold white]~ Update Manager ~[/bold white]\n\n"
                    "[dim]\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510[/dim]\n"
                    "[dim]\u2502[/dim]  Scanning for updates and validating  [dim]\u2502[/dim]\n"
                    "[dim]\u2502[/dim]  your trading environment ...         [dim]\u2502[/dim]\n"
                    "[dim]\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518[/dim]"
                )
            ),
            border_style="cyan",
            padding=(1, 4),
            title="[bold cyan] \u2500\u2500 System Update \u2500\u2500 [/bold cyan]",
        )
    )

    update_steps = [
        "Version Check",
        "Pull / Upgrade",
        "OpenClaw",
        "Plugins",
        "Config Validation",
    ]
    total_steps = len(update_steps)
    results: list[tuple[str, bool, str]] = []

    # ── Step 1: Version check ───────────────────────────────────────────────
    _update_step(1, total_steps, update_steps[0])

    current_version = _get_installed_version()
    is_editable = _is_editable_install()
    install_label = "editable (dev)" if is_editable else "pip package"

    version_table = Table(
        show_header=False, show_lines=False, box=None, padding=(0, 2),
    )
    version_table.add_column("Label", style="dim")
    version_table.add_column("Value", style="bold")
    if current_version:
        version_table.add_row(
            "  \u251c Current version",
            f"[bold green]{current_version}[/bold green]",
        )
    else:
        version_table.add_row(
            "  \u251c Current version",
            "[yellow]not installed as package[/yellow]",
        )
    version_table.add_row(
        "  \u2514 Install type",
        f"[cyan]{install_label}[/cyan]",
    )
    console.print(version_table)
    results.append(("Version Check", True, current_version or "unknown"))

    # ── Step 2: Pull / Upgrade ──────────────────────────────────────────────
    _update_step(2, total_steps, update_steps[1])

    if is_editable:
        console.print("    [dim italic]Pulling latest source...[/dim italic]")
        ok, out = _test_command(["git", "-C", str(_REPO), "pull", "--ff-only"], timeout=30)
        if ok:
            git_msg = out.splitlines()[-1] if out else "up to date"
            console.print(f"    [green]\u2713[/green] Git pull    [green]{git_msg}[/green]")
            results.append(("Git Pull", True, git_msg))
        else:
            console.print(f"    [red]\u2717[/red] Git pull    [yellow]{out[:100]}[/yellow]")
            console.print("      [dim]\u2514 You may need to commit or stash local changes first.[/dim]")
            results.append(("Git Pull", False, out[:60]))

        console.print("    [dim italic]Re-installing in editable mode...[/dim italic]")
        ok, out = _test_command(
            [sys.executable, "-m", "pip", "install", "-e", f"{_REPO}[all]", "-q"],
            timeout=120,
        )
        if ok:
            console.print(f"    [green]\u2713[/green] Reinstall   [green]OK[/green]")
            results.append(("Reinstall", True, "OK"))
        else:
            console.print(f"    [red]\u2717[/red] Reinstall   [yellow]{out[:100]}[/yellow]")
            results.append(("Reinstall", False, out[:60]))
    else:
        console.print("    [dim italic]Upgrading pro-trader package...[/dim italic]")
        ok, out = _test_command(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pro-trader[all]", "-q"],
            timeout=120,
        )
        if ok:
            console.print(f"    [green]\u2713[/green] Upgrade     [green]OK[/green]")
            results.append(("Upgrade", True, "OK"))
        else:
            console.print(f"    [red]\u2717[/red] Upgrade     [yellow]{out[:100]}[/yellow]")
            results.append(("Upgrade", False, out[:60]))

    # Show version diff
    new_version = _get_installed_version(fresh=True)
    if new_version and new_version != current_version:
        console.print()
        console.print(
            Panel(
                Align.center(
                    Text.from_markup(
                        "[dim]Old[/dim]  [bold red]{old}[/bold red]  "
                        "[bold white]\u2500\u2500\u25b6[/bold white]  "
                        "[bold green]{new}[/bold green]  [dim]New[/dim]".format(
                            old=current_version or "???",
                            new=new_version,
                        )
                    )
                ),
                border_style="green",
                title="[bold green] \u2713 Version Updated [/bold green]",
                padding=(1, 4),
            )
        )
    elif new_version:
        console.print()
        console.print(
            Panel(
                Align.center(
                    Text.from_markup(
                        "[bold cyan]You're already running the latest![/bold cyan]\n\n"
                        f"[dim]v{new_version} -- nothing to upgrade[/dim]"
                    )
                ),
                border_style="cyan",
                title="[bold cyan] \u2713 Up to Date [/bold cyan]",
                padding=(1, 4),
            )
        )

    # ── Step 3: OpenClaw ────────────────────────────────────────────────────
    _update_step(3, total_steps, update_steps[2])

    if shutil.which("openclaw"):
        ok, ver = _test_command(["openclaw", "--version"])
        if ok:
            console.print(f"    [green]\u2713[/green] OpenClaw    [green]{ver.strip()}[/green]")
            results.append(("OpenClaw", True, ver.strip()))
        else:
            console.print(f"    [yellow]\u2717[/yellow] OpenClaw    [yellow]version check failed[/yellow]")
            results.append(("OpenClaw", False, "version check failed"))
    else:
        console.print(f"    [dim]\u2500\u2500[/dim] OpenClaw    [dim]not installed (Discord disabled)[/dim]")
        results.append(("OpenClaw", True, "not installed"))

    # ── Step 4: Plugins ─────────────────────────────────────────────────────
    _update_step(4, total_steps, update_steps[3])

    try:
        from pro_trader import ProTrader
        trader = ProTrader()
        h = trader.health()
        total = sum(len(v) for v in h.values())
        ok_count = sum(
            1 for plugins in h.values()
            for info in plugins.values()
            if info.get("status") == "ok"
        )
        console.print(f"    [green]\u2713[/green] Plugins     [green]{ok_count}/{total} healthy[/green]")
        results.append(("Plugins", ok_count == total, f"{ok_count}/{total}"))
    except Exception as e:
        console.print(f"    [red]\u2717[/red] Plugins     [yellow]{e}[/yellow]")
        results.append(("Plugins", False, str(e)[:60]))

    # ── Step 5: Config validation ───────────────────────────────────────────
    _update_step(5, total_steps, update_steps[4])

    env = _load_env()
    issues: list[str] = []
    if not env:
        issues.append("No .env file -- run: pro-trader setup")
    else:
        for key_name in ("ALPACA_API_KEY", "ANTHROPIC_API_KEY"):
            val = env.get(key_name, "")
            if not val or _is_placeholder(val):
                issues.append(f"{key_name} not configured")

    if issues:
        console.print(f"    [yellow]\u2717[/yellow] Config      [yellow]{len(issues)} issue(s)[/yellow]")
        for issue in issues:
            console.print(f"      [dim]\u2514[/dim] {issue}")
        console.print("      [dim]Run: pro-trader setup  to fix[/dim]")
        results.append(("Config", False, f"{len(issues)} issues"))
    else:
        console.print(f"    [green]\u2713[/green] Config      [green]OK[/green]")
        results.append(("Config", True, "OK"))

    # ── Final summary ───────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold white] Update Results [/bold white]", style="dim"))
    console.print()

    all_ok = all(ok for _, ok, _ in results)
    summary_table = Table(
        show_header=True, show_lines=True, border_style="dim cyan",
        padding=(0, 2),
    )
    summary_table.add_column("Check", style="bold white")
    summary_table.add_column("Status", justify="center", min_width=6)
    summary_table.add_column("Details", style="dim")

    for label, ok, detail in results:
        marker = "[bold green]\u2713 pass[/bold green]" if ok else "[bold red]\u2717 fail[/bold red]"
        summary_table.add_row(label, marker, detail)

    console.print(Padding(summary_table, (0, 4)))

    if all_ok:
        version_display = new_version or current_version or "unknown"
        _celebrate("All checks passed!", "bold green")
        console.print()
        console.print(
            Panel(
                Align.center(
                    Text.from_markup(
                        "[bold green]\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557[/bold green]\n"
                        "[bold green]\u2551[/bold green]  Update complete -- all systems go  [bold green]\u2551[/bold green]\n"
                        "[bold green]\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d[/bold green]\n\n"
                        f"  Version: [bold cyan]{version_display}[/bold cyan]\n\n"
                        "[dim]The markets wait for no one -- get back out there.[/dim]"
                    )
                ),
                border_style="green",
                padding=(1, 4),
                title="[bold green] \u2713 All Systems Go [/bold green]",
            )
        )
    else:
        console.print()
        console.print(
            Panel(
                Align.center(
                    Text.from_markup(
                        "[bold yellow]\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557[/bold yellow]\n"
                        "[bold yellow]\u2551[/bold yellow]  Update finished -- some items need  [bold yellow]\u2551[/bold yellow]\n"
                        "[bold yellow]\u2551[/bold yellow]  your attention (see \u2717 above)       [bold yellow]\u2551[/bold yellow]\n"
                        "[bold yellow]\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d[/bold yellow]\n\n"
                        "[dim]Run [bold]pro-trader setup[/bold] to reconfigure if needed.[/dim]"
                    )
                ),
                border_style="yellow",
                padding=(1, 4),
                title="[bold yellow] \u26a0 Heads Up [/bold yellow]",
            )
        )


# ── Uninstall mode ───────────────────────────────────────────────────────────

def run_uninstall() -> None:
    """Remove Pro-Trader configuration, data, and optionally the package."""

    # ── Farewell banner ─────────────────────────────────────────────────────
    farewell_art = r"""
       _____                 _ _
      / ____|               | | |
     | |  __  ___   ___   __| | |__  _   _  ___
     | | |_ |/ _ \ / _ \ / _` | '_ \| | | |/ _ \
     | |__| | (_) | (_) | (_| | |_) | |_| |  __/
      \_____|\___/ \___/ \__,_|_.__/ \__, |\___|
                                      __/ |
                                     |___/
    """
    console.print()
    console.print(
        Panel(
            Align.center(
                Text.from_markup(
                    f"[bold red]{farewell_art}[/bold red]\n"
                    "[bold white]~ Uninstall Wizard ~[/bold white]\n\n"
                    "[dim]We'll walk through this together -- nothing is deleted[/dim]\n"
                    "[dim]without your say-so.[/dim]"
                )
            ),
            border_style="red",
            padding=(1, 4),
            title="[bold red] \u2500\u2500 Farewell, Trader \u2500\u2500 [/bold red]",
        )
    )

    removed: list[str] = []
    skipped: list[str] = []

    # 1. Inventory what exists
    artifacts: list[tuple[str, Path, str]] = [
        ("User config", _USER_CONFIG, "~/.pro_trader/config.json"),
        ("User config dir", _USER_CONFIG_DIR, "~/.pro_trader/"),
        ("Environment file", _ENV_FILE, ".env"),
    ]

    # Check for logs/results dirs
    logs_dir = _REPO / "logs"
    results_dir = _REPO / "results"
    if logs_dir.exists():
        artifacts.append(("Logs directory", logs_dir, "logs/"))
    if results_dir.exists():
        artifacts.append(("Results directory", results_dir, "results/"))

    # ── Artifact inventory table ────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold white] Artifact Inventory [/bold white]", style="dim red"))
    console.print()

    table = Table(
        show_header=True, show_lines=True, border_style="dim red",
        padding=(0, 2),
    )
    table.add_column("", justify="center", width=3)
    table.add_column("Item", style="bold white")
    table.add_column("Path", style="dim")
    table.add_column("Found", justify="center")

    for label, path, display in artifacts:
        exists = path.exists()
        icon = "[green]\u2713[/green]" if exists else "[dim]\u2500[/dim]"
        status = "[green]exists[/green]" if exists else "[dim]absent[/dim]"
        row_icon = "[red]\u2666[/red]" if exists else "[dim]\u25cb[/dim]"
        table.add_row(row_icon, label, display, status)

    console.print(Padding(table, (0, 4)))
    console.print()

    if not Confirm.ask("  [bold]Proceed with uninstall?[/bold]", default=False):
        console.print()
        console.print(
            Panel(
                Align.center(
                    Text.from_markup(
                        "[bold cyan]Uninstall cancelled -- nothing was touched.[/bold cyan]\n\n"
                        "[dim]Your trading setup lives to fight another day.[/dim]"
                    )
                ),
                border_style="cyan",
                padding=(1, 4),
            )
        )
        return

    # ── Removal phase ───────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold white] Removing Artifacts [/bold white]", style="dim red"))
    console.print()

    # 2. Remove config files
    if _USER_CONFIG.exists():
        if Confirm.ask("  Delete user config (~/.pro_trader/config.json)?", default=True):
            _USER_CONFIG.unlink()
            removed.append("~/.pro_trader/config.json")
            console.print("    [red]\u2713[/red] Deleted   ~/.pro_trader/config.json")
        else:
            skipped.append("~/.pro_trader/config.json")
            console.print("    [yellow]\u2500[/yellow] Kept      ~/.pro_trader/config.json")

    # Remove user config dir if empty
    if _USER_CONFIG_DIR.exists():
        try:
            _USER_CONFIG_DIR.rmdir()  # Only removes if empty
            removed.append("~/.pro_trader/")
            console.print("    [red]\u2713[/red] Deleted   ~/.pro_trader/")
        except OSError:
            skipped.append("~/.pro_trader/ (not empty)")
            console.print("    [yellow]\u2500[/yellow] Kept      ~/.pro_trader/ (not empty)")

    # 3. Remove .env (careful -- might have other project keys)
    if _ENV_FILE.exists():
        if Confirm.ask("  Delete .env file? (contains API keys for this project)", default=False):
            _ENV_FILE.unlink()
            removed.append(".env")
            console.print("    [red]\u2713[/red] Deleted   .env")
        else:
            skipped.append(".env (kept)")
            console.print("    [yellow]\u2500[/yellow] Kept      .env")

    # 4. Remove logs and results
    if logs_dir.exists():
        if Confirm.ask("  Delete logs directory?", default=True):
            shutil.rmtree(logs_dir)
            removed.append("logs/")
            console.print("    [red]\u2713[/red] Deleted   logs/")
        else:
            skipped.append("logs/")
            console.print("    [yellow]\u2500[/yellow] Kept      logs/")

    if results_dir.exists():
        if Confirm.ask("  Delete results directory?", default=False):
            shutil.rmtree(results_dir)
            removed.append("results/")
            console.print("    [red]\u2713[/red] Deleted   results/")
        else:
            skipped.append("results/")
            console.print("    [yellow]\u2500[/yellow] Kept      results/")

    # 5. Uninstall pip package
    current_version = _get_installed_version()
    if current_version:
        console.print()
        console.print(
            f"    [dim]\u251c[/dim] Pro-Trader package installed: "
            f"[bold]{current_version}[/bold]"
        )
        if Confirm.ask("  Uninstall pro-trader pip package?", default=False):
            ok, out = _test_command(
                [sys.executable, "-m", "pip", "uninstall", "pro-trader", "-y"],
                timeout=30,
            )
            if ok:
                removed.append(f"pro-trader package ({current_version})")
                console.print(f"    [red]\u2713[/red] Deleted   pro-trader package ({current_version})")
            else:
                console.print(f"    [red]\u2717[/red] Failed    {out[:120]}")
                skipped.append("pro-trader package")
        else:
            skipped.append("pro-trader package (kept)")
            console.print("    [yellow]\u2500[/yellow] Kept      pro-trader package")

    # ── Summary ─────────────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold white] Uninstall Summary [/bold white]", style="dim"))
    console.print()

    summary_table = Table(
        show_header=True, show_lines=False, border_style="dim",
        padding=(0, 2),
    )
    summary_table.add_column("", justify="center", width=3)
    summary_table.add_column("Item", style="bold")
    summary_table.add_column("Action", justify="center")

    for item in removed:
        summary_table.add_row(
            "[red]\u2717[/red]", item, "[red]removed[/red]",
        )
    for item in skipped:
        summary_table.add_row(
            "[green]\u2713[/green]", item, "[green]kept[/green]",
        )

    if removed or skipped:
        console.print(Padding(summary_table, (0, 4)))

    if not removed:
        console.print(
            Panel(
                Align.center(
                    Text.from_markup(
                        "[bold cyan]Nothing was removed -- your setup is untouched.[/bold cyan]"
                    )
                ),
                border_style="cyan",
                padding=(1, 4),
            )
        )
    else:
        console.print()
        console.print(
            Panel(
                Align.center(
                    Text.from_markup(
                        "[bold white]Until we trade again...[/bold white]\n\n"
                        "[dim]\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510[/dim]\n"
                        "[dim]\u2502[/dim]  To reinstall at any time, run:     [dim]\u2502[/dim]\n"
                        "[dim]\u2502[/dim]                                     [dim]\u2502[/dim]\n"
                        '[dim]\u2502[/dim]  [bold cyan]pip install -e ".[all]"[/bold cyan]            [dim]\u2502[/dim]\n'
                        "[dim]\u2502[/dim]  [bold cyan]pro-trader setup[/bold cyan]                  [dim]\u2502[/dim]\n"
                        "[dim]\u2502[/dim]                                     [dim]\u2502[/dim]\n"
                        "[dim]\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518[/dim]\n\n"
                        "[dim italic]It's been a pleasure trading with you.[/dim italic]"
                    )
                ),
                border_style="red",
                padding=(1, 4),
                title="[bold red] \u2500\u2500 Goodbye \u2500\u2500 [/bold red]",
            )
        )


# ── Internal helpers ─────────────────────────────────────────────────────────

def _get_installed_version(fresh: bool = False) -> str | None:
    """Get the installed pro-trader package version.

    Args:
        fresh: If True, use a subprocess to avoid stale importlib.metadata cache
               (useful after pip install/upgrade in the same process).
    """
    if fresh:
        ok, out = _test_command([
            sys.executable, "-c",
            "from importlib.metadata import version; print(version('pro-trader'))",
        ])
        return out.strip() if ok and out.strip() else None
    try:
        from importlib.metadata import version
        return version("pro-trader")
    except Exception:
        return None


def _is_editable_install() -> bool:
    """Check if pro-trader is installed in editable/dev mode."""
    try:
        from importlib.metadata import distribution
        dist = distribution("pro-trader")
        # Editable installs have a direct_url.json with "editable" or the path matches repo
        direct_url = dist.read_text("direct_url.json")
        if direct_url and "editable" in direct_url:
            return True
    except Exception:
        pass
    # Fallback: check if the package location is the repo itself
    try:
        import pro_trader
        pkg_path = Path(pro_trader.__file__).resolve().parent.parent
        return pkg_path == _REPO
    except Exception:
        return False

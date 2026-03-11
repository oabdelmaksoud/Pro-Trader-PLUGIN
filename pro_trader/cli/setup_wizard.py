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


# ── Wizard Steps ─────────────────────────────────────────────────────────────

def _step_openclaw() -> dict:
    """Step 1: Check OpenClaw installation."""
    console.print("\n[bold cyan]Step 1/6 — OpenClaw Integration[/bold cyan]\n")

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
    console.print("\n[bold cyan]Step 2/6 — Trader Profile[/bold cyan]")
    console.print("[dim]  This helps AI agents personalize analysis to YOUR situation.[/dim]\n")

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
    console.print("  If your portfolio dropped 20% in a month, what would you do?")
    console.print("    1. Sell everything")
    console.print("    2. Sell some to reduce risk")
    console.print("    3. Hold and wait for recovery")
    console.print("    4. Buy more at the lower prices")

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
    console.print("    1. Notify only    — AI analyzes, you trade manually")
    console.print("    2. Suggest        — AI proposes trades, you approve (default)")
    console.print("    3. Semi-auto      — AI auto-trades within conservative limits")
    console.print("    4. Full auto      — AI executes all approved trades")

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
        console.print("\n  [bold yellow]Recovery Plan[/bold yellow]")
        console.print(f"  Account: ${account_size:,.0f} → "
                       f"Target: ${account_size + losses_to_recover:,.0f} "
                       f"(recover ${losses_to_recover:,.0f})")

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

        console.print("\n    1. [green]Conservative rebuild[/green] — Slow, safe, no risk increase")
        console.print("    2. [yellow]Moderate recovery[/yellow]    — Slightly larger positions")
        console.print("    3. [red]Aggressive recovery[/red]   — Maximum acceptable risk")

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
            console.print(f"\n  [dim]Weekly target: ${weekly_target:,.0f}/wk ({weekly_pct:.1f}% of account)[/dim]")
            if weekly_pct > 10:
                console.print("  [red]That pace is very aggressive — AI will prioritize risk management.[/red]")
            elif weekly_pct > 5:
                console.print("  [yellow]Ambitious but achievable with discipline.[/yellow]")

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

    # Summary
    console.print("\n  [bold]Profile Summary[/bold]")
    summary = Table(show_header=False)
    summary.add_column("Key", style="bold")
    summary.add_column("Value")
    summary.add_row("Account", f"${account_size:,.0f}")
    if monthly_deposit > 0:
        summary.add_row("Monthly deposit", f"${monthly_deposit:,.0f}")
    if recovery_mode:
        summary.add_row("Recovery target", f"${account_size + losses_to_recover:,.0f}")
        summary.add_row("Recovery strategy", recovery_strategy)
        if loss_cause:
            summary.add_row("Loss cause", loss_cause)
    summary.add_row("Risk tolerance", risk_tolerance)
    summary.add_row("Loss reaction", reaction_to_loss)
    summary.add_row("Max single loss", f"${worst_acceptable_loss:,.0f}")
    summary.add_row("Position sizing", position_sizing_method)
    summary.add_row("Style", f"{trading_style} ({period_map.get(trading_style, 'days')})")
    summary.add_row("Availability", market_hours)
    summary.add_row("Assets", ", ".join(preferred_assets))
    summary.add_row("Experience", exp_map[exp_choice])
    summary.add_row("Goal", goal_map[goal_choice])
    summary.add_row("Autonomy", autonomy_level)
    console.print(summary)

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
    console.print(
        "\n[bold cyan]Step 3/6 — Broker Configuration[/bold cyan]\n"
    )

    broker_names = list(_BROKER_CONFIGS.keys())
    for i, name in enumerate(broker_names, 1):
        cfg = _BROKER_CONFIGS[name]
        console.print(f"    {i}. {cfg['label']}")
    console.print(f"    s. Skip (no broker)")

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

    console.print(f"  [green]Primary broker: {primary}[/green]")
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
    """Step 3: Configure LLM provider."""
    console.print("\n[bold cyan]Step 4/6 — LLM Provider[/bold cyan]\n")

    providers = {
        "1": ("anthropic", "ANTHROPIC_API_KEY", "Anthropic (Claude)"),
        "2": ("openai", "OPENAI_API_KEY", "OpenAI (GPT)"),
        "3": ("google", "GOOGLE_API_KEY", "Google (Gemini)"),
    }

    console.print("  Available providers:")
    for num, (_, _, label) in providers.items():
        marker = " (recommended)" if num == "1" else ""
        console.print(f"    {num}. {label}{marker}")

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
    """Step 4: Verify Discord channels."""
    console.print("\n[bold cyan]Step 5/6 — Discord Channels[/bold cyan]\n")

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
    """Step 5: Review and toggle plugins."""
    console.print("\n[bold cyan]Step 6/6 — Plugin Configuration[/bold cyan]\n")

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
    console.print(Panel(
        "[bold]Pro-Trader Setup Wizard[/bold]\n"
        "Configure Pro-Trader as an OpenClaw plugin.\n"
        "Press Ctrl+C at any time to cancel.",
        style="cyan",
    ))

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
    console.print("\n[bold cyan]Summary[/bold cyan]\n")

    llm_provider = env.pop("_llm_provider", "anthropic")

    summary = Table(show_header=False)
    summary.add_column("Key", style="bold")
    summary.add_column("Value")

    alpaca_url = env.get("ALPACA_BASE_URL", "")
    summary.add_row("Account", f"${trader_profile.get('account_size', 0):,.0f}")
    summary.add_row("Risk tolerance", trader_profile.get("risk_tolerance", "moderate"))
    if trader_profile.get("recovery_mode"):
        summary.add_row("Recovery mode", f"recover ${trader_profile.get('losses_to_recover', 0):,.0f}")
    broker_display = primary_broker or "none"
    if primary_broker == "alpaca":
        broker_display += " (paper)" if "paper" in alpaca_url else " (LIVE)"
    if len(selected_brokers) > 1:
        broker_display += f" + {len(selected_brokers) - 1} more"
    summary.add_row("Broker", broker_display)
    summary.add_row("LLM provider", llm_provider)
    summary.add_row("OpenClaw", "available" if openclaw_info.get("openclaw_available") else "not installed")
    summary.add_row("Plugins toggled", str(len(plugin_cfg)) if plugin_cfg else "none")
    summary.add_row(".env location", str(_ENV_FILE))
    summary.add_row("Config location", str(_USER_CONFIG))
    console.print(summary)

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
    console.print(Panel(
        "[bold green]Setup complete![/bold green]\n\n"
        "Next steps:\n"
        "  pro-trader health         — verify all systems\n"
        "  pro-trader plugin list    — see active plugins\n"
        "  pro-trader analyze NVDA   — test the pipeline\n"
        "  pro-trader setup --check  — re-check anytime\n"
        "  pro-trader setup --update — update Pro-Trader",
        style="green",
    ))


# ── Update mode ──────────────────────────────────────────────────────────────

def run_update() -> None:
    """Update Pro-Trader installation and re-validate config."""
    console.print(Panel("[bold]Pro-Trader Update[/bold]", style="cyan"))

    # 1. Show current version
    current_version = _get_installed_version()
    if current_version:
        console.print(f"  Current version: [bold]{current_version}[/bold]")
    else:
        console.print("  [yellow]Pro-Trader not installed as package[/yellow]")

    # 2. Check for source vs pip install
    is_editable = _is_editable_install()

    if is_editable:
        console.print("  Install type:    [cyan]editable (dev)[/cyan]\n")
        console.print("  Pulling latest source...")
        ok, out = _test_command(["git", "-C", str(_REPO), "pull", "--ff-only"], timeout=30)
        if ok:
            console.print(f"  [green]Git pull OK[/green]: {out.splitlines()[-1] if out else 'up to date'}")
        else:
            console.print(f"  [yellow]Git pull failed[/yellow]: {out[:120]}")
            console.print("  [dim]You may need to commit or stash local changes first.[/dim]")

        # Re-install in editable mode to pick up new entry points
        console.print("  Re-installing in editable mode...")
        ok, out = _test_command(
            [sys.executable, "-m", "pip", "install", "-e", f"{_REPO}[all]", "-q"],
            timeout=120,
        )
        if ok:
            console.print("  [green]Reinstall OK[/green]")
        else:
            console.print(f"  [yellow]Reinstall issue[/yellow]: {out[:120]}")
    else:
        console.print("  Install type:    [cyan]pip package[/cyan]\n")
        console.print("  Upgrading pro-trader...")
        ok, out = _test_command(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pro-trader[all]", "-q"],
            timeout=120,
        )
        if ok:
            console.print("  [green]Upgrade OK[/green]")
        else:
            console.print(f"  [yellow]Upgrade issue[/yellow]: {out[:120]}")

    # 3. Show new version (fresh=True to avoid stale importlib cache)
    new_version = _get_installed_version(fresh=True)
    if new_version and new_version != current_version:
        console.print(f"\n  Updated: {current_version} → [bold green]{new_version}[/bold green]")
    elif new_version:
        console.print(f"\n  Already at latest: [bold]{new_version}[/bold]")

    # 4. Re-validate OpenClaw compatibility
    console.print("\n  Checking OpenClaw compatibility...")
    if shutil.which("openclaw"):
        ok, ver = _test_command(["openclaw", "--version"])
        if ok:
            console.print(f"  [green]OpenClaw OK[/green]: {ver}")
        else:
            console.print(f"  [yellow]OpenClaw version check failed[/yellow]")
    else:
        console.print("  [dim]OpenClaw not installed (Discord disabled)[/dim]")

    # 5. Re-validate plugins load
    console.print("  Checking plugins...")
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
        console.print(f"  [green]Plugins OK[/green]: {ok_count}/{total} healthy")
    except Exception as e:
        console.print(f"  [yellow]Plugin check failed[/yellow]: {e}")

    # 6. Validate existing config
    env = _load_env()
    issues: list[str] = []
    if not env:
        issues.append("No .env file — run: pro-trader setup")
    else:
        for key_name in ("ALPACA_API_KEY", "ANTHROPIC_API_KEY"):
            val = env.get(key_name, "")
            if not val or _is_placeholder(val):
                issues.append(f"{key_name} not configured")

    if issues:
        console.print("\n  [yellow]Config issues:[/yellow]")
        for issue in issues:
            console.print(f"    - {issue}")
        console.print("  [dim]Run: pro-trader setup  to fix[/dim]")
    else:
        console.print("  [green]Config OK[/green]")

    console.print(Panel("[bold green]Update complete![/bold green]", style="green"))


# ── Uninstall mode ───────────────────────────────────────────────────────────

def run_uninstall() -> None:
    """Remove Pro-Trader configuration, data, and optionally the package."""
    console.print(Panel(
        "[bold red]Pro-Trader Uninstall[/bold red]\n"
        "This will remove Pro-Trader configuration files and data.",
        style="red",
    ))

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

    console.print("\n  [bold]Files and directories to remove:[/bold]\n")
    table = Table(show_header=True, show_lines=False)
    table.add_column("Item", style="bold")
    table.add_column("Path", style="dim")
    table.add_column("Exists")

    for label, path, display in artifacts:
        exists = path.exists()
        status = "[green]yes[/green]" if exists else "[dim]no[/dim]"
        table.add_row(label, display, status)
    console.print(table)

    if not Confirm.ask("\n  Proceed with uninstall?", default=False):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    # 2. Remove config files
    if _USER_CONFIG.exists():
        if Confirm.ask("  Delete user config (~/.pro_trader/config.json)?", default=True):
            _USER_CONFIG.unlink()
            removed.append("~/.pro_trader/config.json")
        else:
            skipped.append("~/.pro_trader/config.json")

    # Remove user config dir if empty
    if _USER_CONFIG_DIR.exists():
        try:
            _USER_CONFIG_DIR.rmdir()  # Only removes if empty
            removed.append("~/.pro_trader/")
        except OSError:
            skipped.append("~/.pro_trader/ (not empty)")

    # 3. Remove .env (careful — might have other project keys)
    if _ENV_FILE.exists():
        if Confirm.ask("  Delete .env file? (contains API keys for this project)", default=False):
            _ENV_FILE.unlink()
            removed.append(".env")
        else:
            skipped.append(".env (kept)")

    # 4. Remove logs and results
    if logs_dir.exists():
        if Confirm.ask("  Delete logs directory?", default=True):
            shutil.rmtree(logs_dir)
            removed.append("logs/")
        else:
            skipped.append("logs/")

    if results_dir.exists():
        if Confirm.ask("  Delete results directory?", default=False):
            shutil.rmtree(results_dir)
            removed.append("results/")
        else:
            skipped.append("results/")

    # 5. Uninstall pip package
    current_version = _get_installed_version()
    if current_version:
        console.print(f"\n  Pro-Trader package installed: [bold]{current_version}[/bold]")
        if Confirm.ask("  Uninstall pro-trader pip package?", default=False):
            ok, out = _test_command(
                [sys.executable, "-m", "pip", "uninstall", "pro-trader", "-y"],
                timeout=30,
            )
            if ok:
                removed.append(f"pro-trader package ({current_version})")
                console.print("  [green]Package uninstalled[/green]")
            else:
                console.print(f"  [red]Uninstall failed[/red]: {out[:120]}")
                skipped.append("pro-trader package")
        else:
            skipped.append("pro-trader package (kept)")

    # 6. Summary
    console.print("\n[bold]Uninstall Summary[/bold]\n")

    if removed:
        console.print("  [red]Removed:[/red]")
        for item in removed:
            console.print(f"    - {item}")

    if skipped:
        console.print("  [yellow]Kept:[/yellow]")
        for item in skipped:
            console.print(f"    - {item}")

    if not removed:
        console.print("  [dim]Nothing was removed.[/dim]")
    else:
        console.print(Panel(
            "[bold]Pro-Trader has been uninstalled.[/bold]\n\n"
            "To reinstall:\n"
            '  pip install -e ".[all]"\n'
            "  pro-trader setup",
            style="yellow",
        ))


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

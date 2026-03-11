"""
Pro-Trader Setup Wizard — interactive first-time configuration.

Guides users through:
  1. OpenClaw connectivity check
  2. Trader Profile (account size, risk, goals, recovery)
  3. Broker API keys (Alpaca)
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
        f"  Max risk per trade (%)",
        default=str(profile.get("max_loss_per_trade_pct", rd["max_loss_per_trade"])),
    )
    max_daily = Prompt.ask(
        f"  Max daily loss before stopping (%)",
        default=str(profile.get("max_daily_loss_pct", rd["max_daily_loss"])),
    )
    max_dd = Prompt.ask(
        f"  Max portfolio drawdown before full halt (%)",
        default=str(profile.get("max_drawdown_pct", rd["max_drawdown"])),
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

    # ── Recovery Plan ─────────────────────────────────────────────
    recovery_timeline_weeks = None
    recovery_strategy = "moderate"

    if recovery_mode:
        console.print("\n  [bold yellow]Recovery Plan[/bold yellow]")
        console.print(f"  Account: ${account_size:,.0f} → "
                       f"Target: ${account_size + losses_to_recover:,.0f} "
                       f"(recover ${losses_to_recover:,.0f})")

        timeline = Prompt.ask(
            "  Recovery timeline (weeks, or 'no_rush')",
            default=str(profile.get("recovery_timeline_weeks", "no_rush")),
        )
        if timeline.lower() != "no_rush":
            try:
                recovery_timeline_weeks = int(timeline)
            except ValueError:
                pass

        console.print("    1. [green]Conservative rebuild[/green] — Slow, safe, no risk increase")
        console.print("    2. [yellow]Moderate recovery[/yellow]    — Slightly larger positions")
        console.print("    3. [red]Aggressive recovery[/red]   — Maximum acceptable risk")

        rec_map = {"1": "conservative_rebuild", "2": "moderate", "3": "aggressive"}
        current_rec = profile.get("recovery_strategy", "moderate")
        default_rec = {"conservative_rebuild": "1", "moderate": "2", "aggressive": "3"}.get(current_rec, "2")
        rec_choice = Prompt.ask("  Recovery strategy", choices=["1", "2", "3"], default=default_rec)
        recovery_strategy = rec_map[rec_choice]

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
        "account_size": account_size,
        "peak_account_value": peak_account_value,
        "losses_to_recover": losses_to_recover,
        "recovery_mode": recovery_mode,
        "risk_tolerance": risk_tolerance,
        "max_loss_per_trade_pct": float(max_loss_trade),
        "max_daily_loss_pct": float(max_daily),
        "max_drawdown_pct": float(max_dd),
        "trading_style": trading_style,
        "holding_period": period_map.get(trading_style, "days"),
        "preferred_assets": preferred_assets,
        "experience_level": exp_map[exp_choice],
        "trading_goal": goal_map[goal_choice],
        "recovery_timeline_weeks": recovery_timeline_weeks,
        "recovery_strategy": recovery_strategy,
    }

    # Summary
    console.print("\n  [bold]Profile Summary[/bold]")
    summary = Table(show_header=False)
    summary.add_column("Key", style="bold")
    summary.add_column("Value")
    summary.add_row("Account", f"${account_size:,.0f}")
    if recovery_mode:
        summary.add_row("Recovery target", f"${account_size + losses_to_recover:,.0f}")
        summary.add_row("Recovery strategy", recovery_strategy)
    summary.add_row("Risk tolerance", risk_tolerance)
    summary.add_row("Style", f"{trading_style} ({period_map.get(trading_style, 'days')})")
    summary.add_row("Assets", ", ".join(preferred_assets))
    summary.add_row("Experience", exp_map[exp_choice])
    summary.add_row("Goal", goal_map[goal_choice])
    console.print(summary)

    return result


def _step_broker(env: dict[str, str]) -> dict[str, str]:
    """Step 3: Configure broker API keys."""
    console.print("\n[bold cyan]Step 3/6 — Broker Configuration (Alpaca)[/bold cyan]\n")

    current_key = env.get("ALPACA_API_KEY", "")
    current_secret = env.get("ALPACA_SECRET_KEY", "")
    current_url = env.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    has_key = current_key and not _is_placeholder(current_key)
    has_secret = current_secret and not _is_placeholder(current_secret)

    if has_key and has_secret:
        console.print(f"  Existing API key:    {_mask(current_key)}")
        console.print(f"  Existing secret:     {_mask(current_secret)}")
        console.print(f"  Base URL:            {current_url}")
        if not Confirm.ask("  Update broker keys?", default=False):
            return env

    api_key = Prompt.ask(
        "  Alpaca API key",
        default=current_key if has_key else "",
    )
    secret_key = Prompt.ask(
        "  Alpaca secret key",
        default=current_secret if has_secret else "",
        password=True,
    )

    paper = Confirm.ask("  Use paper trading?", default=True)
    base_url = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"

    if not paper:
        console.print("  [bold red]WARNING: Live trading selected. Real money at risk.[/bold red]")
        if not Confirm.ask("  Confirm live trading?", default=False):
            base_url = "https://paper-api.alpaca.markets"
            console.print("  [green]Switched back to paper trading.[/green]")

    env["ALPACA_API_KEY"] = api_key
    env["ALPACA_SECRET_KEY"] = secret_key
    env["ALPACA_BASE_URL"] = base_url

    # Validate connection
    if api_key and not _is_placeholder(api_key):
        console.print("  Testing Alpaca connection...", end=" ")
        try:
            test_env = os.environ.copy()
            test_env["APCA_API_KEY_ID"] = api_key
            test_env["APCA_API_SECRET_KEY"] = secret_key
            test_env["APCA_API_BASE_URL"] = base_url
            r = subprocess.run(
                [sys.executable, "-c",
                 "import alpaca_trade_api as t; a=t.REST(); print(a.get_account().status)"],
                capture_output=True, text=True, timeout=15, env=test_env,
            )
            if r.returncode == 0 and r.stdout.strip():
                console.print(f"[green]{r.stdout.strip()}[/green]")
            else:
                console.print(f"[yellow]could not verify ({r.stderr.strip()[:80]})[/yellow]")
        except Exception:
            console.print("[yellow]skipped (alpaca-trade-api not installed)[/yellow]")

    return env


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

    # Step 3: Broker
    env = _step_broker(env)

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
    summary.add_row("Broker", "paper" if "paper" in alpaca_url else "LIVE")
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

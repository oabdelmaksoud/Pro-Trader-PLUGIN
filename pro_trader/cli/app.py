"""
Pro-Trader CLI — plugin-aware command-line interface.

Usage:
    pro-trader analyze NVDA
    pro-trader analyze /METH26 --no-dry-run
    pro-trader scan --watchlist
    pro-trader plugin list
    pro-trader plugin enable polygon
    pro-trader monitor start
    pro-trader config show
    pro-trader setup
    pro-trader setup --check
    pro-trader setup --update
    pro-trader setup --uninstall
    pro-trader health
    pro-trader sync
    pro-trader sync --apply
    pro-trader broker list
    pro-trader broker add
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

try:
    import typer
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("Missing dependencies. Run: pip install typer rich")
    sys.exit(1)

# Ensure project root is importable
_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO))

console = Console()
app = typer.Typer(name="pro-trader", help="Pro-Trader Plugin Framework CLI")


# ── Analyze ──────────────────────────────────────────────────────────────────

@app.command()
def analyze(
    ticker: str = typer.Argument(..., help="Symbol to analyze (NVDA, /METH26)"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Simulate without executing"),
    threshold: float = typer.Option(7.0, help="Score threshold for trade"),
):
    """Run full analysis pipeline on a single ticker."""
    from pro_trader import ProTrader

    console.print(f"\n[bold]Pro-Trader Analysis — {ticker}[/bold]")
    console.print(f"Dry run: {dry_run} | Threshold: {threshold}\n")

    trader = ProTrader(config={"score_threshold": threshold})
    signal = trader.analyze(ticker, dry_run=dry_run)

    _print_signal(signal)


# ── Scan ─────────────────────────────────────────────────────────────────────

@app.command()
def scan(
    tickers: list[str] = typer.Argument(None, help="Tickers to scan"),
    watchlist: bool = typer.Option(False, "--watchlist", help="Use configured watchlist"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    top: int = typer.Option(5, help="Show top N results"),
):
    """Scan multiple tickers and rank by score."""
    from pro_trader import ProTrader

    trader = ProTrader()

    if watchlist or not tickers:
        tickers = None  # Use configured watchlist

    signals = trader.scan(tickers, dry_run=dry_run)

    table = Table(title="Scan Results")
    table.add_column("Rank", style="dim")
    table.add_column("Ticker", style="bold")
    table.add_column("Direction")
    table.add_column("Score")
    table.add_column("Confidence")
    table.add_column("Type")
    table.add_column("Threshold")

    for i, sig in enumerate(signals[:top], 1):
        color = "green" if sig.meets_threshold else "red"
        table.add_row(
            str(i), sig.ticker, sig.direction.value,
            f"[{color}]{sig.score:.1f}[/{color}]",
            str(sig.confidence), sig.asset_type,
            "MET" if sig.meets_threshold else "-"
        )

    console.print(table)


# ── Plugin Management ────────────────────────────────────────────────────────

plugin_app = typer.Typer(help="Plugin management commands")
app.add_typer(plugin_app, name="plugin")


@plugin_app.command("list")
def plugin_list():
    """List all registered plugins."""
    from pro_trader import ProTrader

    trader = ProTrader()
    all_plugins = trader.plugins.get_all_plugins()

    table = Table(title="Registered Plugins")
    table.add_column("Category", style="bold")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("Description")

    for category, plugins in all_plugins.items():
        for plugin in plugins:
            status = "[green]enabled[/green]" if plugin.enabled else "[red]disabled[/red]"
            table.add_row(category, plugin.name, plugin.version, status, plugin.description)

    console.print(table)


@plugin_app.command("enable")
def plugin_enable(name: str = typer.Argument(..., help="Plugin name")):
    """Enable a plugin."""
    from pro_trader import ProTrader
    trader = ProTrader()
    if trader.plugins.enable(name):
        console.print(f"[green]Enabled plugin: {name}[/green]")
    else:
        console.print(f"[red]Plugin not found: {name}[/red]")


@plugin_app.command("disable")
def plugin_disable(name: str = typer.Argument(..., help="Plugin name")):
    """Disable a plugin."""
    from pro_trader import ProTrader
    trader = ProTrader()
    if trader.plugins.disable(name):
        console.print(f"[yellow]Disabled plugin: {name}[/yellow]")
    else:
        console.print(f"[red]Plugin not found: {name}[/red]")


@plugin_app.command("health")
def plugin_health():
    """Show plugin health status."""
    from pro_trader import ProTrader
    trader = ProTrader()
    health = trader.health()

    for category, plugins in health.items():
        if plugins:
            console.print(f"\n[bold]{category}[/bold]:")
            for name, status in plugins.items():
                color = "green" if status.get("status") == "ok" else "red"
                console.print(f"  [{color}]{name}: {status.get('status', '?')}[/{color}]")


# ── Config ───────────────────────────────────────────────────────────────────

@app.command()
def config(
    key: str = typer.Argument(None, help="Config key (dot notation)"),
    value: str = typer.Option(None, help="Value to set"),
):
    """Show or set configuration values."""
    from pro_trader.core.config import Config
    cfg = Config()

    if key and value:
        cfg.set(key, value)
        console.print(f"[green]Set {key} = {value}[/green]")
    elif key:
        val = cfg.get(key)
        console.print(f"{key} = {json.dumps(val, indent=2)}")
    else:
        console.print(json.dumps(cfg.data, indent=2))


# ── Health ───────────────────────────────────────────────────────────────────

@app.command()
def health():
    """Show system health."""
    from pro_trader import ProTrader
    trader = ProTrader()
    console.print(json.dumps(trader.health(), indent=2))


# ── Monitor ──────────────────────────────────────────────────────────────────

@app.command()
def monitor(action: str = typer.Argument("status", help="start | stop | status")):
    """Run background monitors."""
    from pro_trader import ProTrader

    trader = ProTrader()
    monitors = trader.plugins.get_plugins("monitor")

    if action == "status":
        table = Table(title="Monitors")
        table.add_column("Name")
        table.add_column("Interval")
        table.add_column("State")
        for m in monitors:
            state = m.get_state()
            table.add_row(m.name, f"{m.interval}s", json.dumps(state)[:80])
        console.print(table)

    elif action == "check":
        for m in monitors:
            console.print(f"\n[bold]{m.name}[/bold]:")
            alerts = m.check()
            for alert in alerts:
                color = "red" if alert["severity"] == "warning" else "white"
                console.print(f"  [{color}]{alert['message']}[/{color}]")
            if not alerts:
                console.print("  No alerts")

    else:
        console.print(f"Unknown action: {action}. Use: status, check")


# ── Dashboard ───────────────────────────────────────────────────────────────

@app.command()
def dashboard(
    port: int = typer.Option(8080, help="HTTP port"),
    open_browser: bool = typer.Option(False, "--open", help="Auto-open browser"),
):
    """Launch the real-time trading dashboard."""
    from pro_trader import ProTrader
    from pro_trader.plugins.dashboard.server import start

    trader = ProTrader()
    start(port=port, open_browser=open_browser, trader=trader)


# ── Setup Wizard ────────────────────────────────────────────────────────────

@app.command()
def setup(
    check: bool = typer.Option(False, "--check", help="Verify existing setup without changes"),
    update: bool = typer.Option(False, "--update", help="Update existing installation"),
    uninstall: bool = typer.Option(False, "--uninstall", help="Remove Pro-Trader config and package"),
):
    """Interactive setup wizard for first-time configuration."""
    from pro_trader.cli.setup_wizard import run_wizard, run_check, run_update, run_uninstall

    flags = sum([check, update, uninstall])
    if flags > 1:
        console.print("[red]Only one of --check, --update, --uninstall can be used at a time.[/red]")
        raise typer.Exit(1)

    try:
        if uninstall:
            run_uninstall()
        elif update:
            run_update()
        elif check:
            run_check()
        else:
            run_wizard()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")


# ── Broker Management ────────────────────────────────────────────────────────

broker_app = typer.Typer(help="Manage broker connections")
app.add_typer(broker_app, name="broker")


@broker_app.command("list")
def broker_list():
    """List all broker plugins and their status."""
    from pro_trader import ProTrader

    trader = ProTrader()
    brokers = trader.plugins.get_plugins("broker")
    primary = trader.config.get("primary_broker", "")

    table = Table(title="Broker Plugins")
    table.add_column("Name", style="bold")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("Assets")
    table.add_column("Primary")
    table.add_column("Description")

    for b in brokers:
        status = "[green]enabled[/green]" if b.enabled else "[red]disabled[/red]"
        is_primary = "[bold green]YES[/bold green]" if b.name == primary else ""
        assets = ", ".join(getattr(b, "supported_assets", []))
        table.add_row(b.name, b.version, status, assets, is_primary, b.description)

    if not brokers:
        console.print("[yellow]No broker plugins loaded.[/yellow]")
    else:
        console.print(table)


@broker_app.command("add")
def broker_add():
    """Add a new broker connection (mini setup wizard)."""
    from pro_trader.cli.setup_wizard import (
        _BROKER_CONFIGS, _configure_single_broker, _load_env, _save_env,
    )
    from rich.prompt import Prompt

    env = _load_env()
    broker_names = list(_BROKER_CONFIGS.keys())

    console.print("\n[bold]Available brokers:[/bold]")
    for i, name in enumerate(broker_names, 1):
        cfg = _BROKER_CONFIGS[name]
        console.print(f"  {i}. {cfg['label']}")

    choice = Prompt.ask("Select broker", default="1")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(broker_names):
            broker_name = broker_names[idx]
        else:
            console.print("[red]Invalid choice.[/red]")
            raise typer.Exit(1)
    except ValueError:
        if choice in broker_names:
            broker_name = choice
        else:
            console.print("[red]Invalid choice.[/red]")
            raise typer.Exit(1)

    _configure_single_broker(broker_name, env)
    _save_env(env)
    console.print(f"\n[green]Broker '{broker_name}' configured. Credentials saved to .env[/green]")


@broker_app.command("test")
def broker_test():
    """Test all connected broker connections."""
    from pro_trader import ProTrader

    trader = ProTrader()
    brokers = trader.plugins.get_plugins("broker")

    if not brokers:
        console.print("[yellow]No broker plugins loaded.[/yellow]")
        return

    for b in brokers:
        console.print(f"\n[bold]{b.name}[/bold]:", end=" ")
        try:
            health = b.health_check()
            status = health.get("status", "unknown")
            if status == "ok":
                console.print(f"[green]{status}[/green]")
            else:
                console.print(f"[yellow]{status}[/yellow]")
            for k, v in health.items():
                if k not in ("name", "version", "status"):
                    console.print(f"  {k}: {v}")
        except Exception as e:
            console.print(f"[red]error: {e}[/red]")


# ── Sync ────────────────────────────────────────────────────────────────────

@app.command()
def sync(
    broker_name: str = typer.Option(None, "--broker", "-b", help="Broker to sync from (default: primary)"),
    apply: bool = typer.Option(False, "--apply", help="Write synced values to config"),
):
    """Sync trader profile from live broker account data."""
    from pro_trader import ProTrader

    trader = ProTrader()
    brokers = trader.plugins.get_plugins("broker")

    if not brokers:
        console.print("[red]No broker plugins available.[/red]")
        raise typer.Exit(1)

    # Find target broker
    if broker_name:
        target = next((b for b in brokers if b.name == broker_name), None)
    else:
        primary = trader.config.get("primary_broker", "")
        target = next((b for b in brokers if b.name == primary), None)
        if not target:
            target = brokers[0]

    if not target:
        console.print(f"[red]Broker '{broker_name}' not found or not enabled.[/red]")
        raise typer.Exit(1)

    console.print(f"\nSyncing from [bold]{target.name}[/bold]...")
    summary = target.get_account_summary()

    table = Table(title=f"Account Summary — {target.name}")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Account ID", summary.account_id or "-")
    table.add_row("Status", summary.status or "-")
    table.add_row("Equity", f"${summary.equity:,.2f}")
    table.add_row("Cash", f"${summary.cash:,.2f}")
    table.add_row("Buying Power", f"${summary.buying_power:,.2f}")
    table.add_row("Today P&L", f"${summary.today_pnl:,.2f}")
    table.add_row("Open Positions", str(summary.open_positions))
    if summary.position_symbols:
        table.add_row("Symbols", ", ".join(summary.position_symbols[:15]))
    table.add_row("PDT", str(summary.pattern_day_trader))
    table.add_row("Assets", ", ".join(summary.supported_assets) or "-")
    console.print(table)

    if apply:
        from pro_trader.cli.setup_wizard import _load_user_config, _save_user_config
        cfg = _load_user_config()
        profile = cfg.get("trader_profile", {})
        if summary.equity > 0:
            profile["account_size"] = summary.equity
            cfg["account_value"] = summary.equity
        cfg["trader_profile"] = profile
        _save_user_config(cfg)
        console.print(f"\n[green]Updated config with equity=${summary.equity:,.2f}[/green]")
    else:
        console.print(f"\n[dim]Use --apply to write values to config.[/dim]")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _print_signal(signal):
    """Pretty-print a signal."""
    color = "green" if signal.meets_threshold else "red"
    console.print(f"\n[bold]{signal.direction.value} {signal.ticker}[/bold]")
    console.print(f"  Score: [{color}]{signal.score:.1f}/10[/{color}]")
    console.print(f"  Confidence: {signal.confidence}/10")
    console.print(f"  Price: ${signal.price:.2f}")
    console.print(f"  Type: {signal.asset_type}")
    console.print(f"  Source: {signal.source}")
    if signal.meets_threshold:
        console.print(f"  [green]THRESHOLD MET[/green]")
    else:
        console.print(f"  [dim]Below threshold[/dim]")


def main():
    app()


if __name__ == "__main__":
    main()

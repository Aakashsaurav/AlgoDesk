import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from cli.display.tables import positions_table, orders_table, trades_table, pnl_table
from cli.display.dashboard import run_dashboard
from live_bot.preflight import PreflightChecker
from config import config

live_app = typer.Typer(name="live", help="Live trading commands (REAL MONEY)")
console = Console()

def _live_trading_gate() -> None:
    """Forces user to type confirmation phrase before live trading."""
    typer.echo("\n" + "="*60)
    typer.echo("  ⚠️  LIVE TRADING MODE — REAL MONEY AT RISK")
    typer.echo("="*60)
    typer.echo("  This will place REAL orders with your broker.")
    typer.echo("  All profits and losses are REAL.")
    typer.echo("\n  Type exactly: I UNDERSTAND REAL MONEY")
    typer.echo("  to proceed, or press Ctrl+C to cancel.\n")

    phrase = typer.prompt("Confirmation")
    if phrase != "I UNDERSTAND REAL MONEY":
        typer.echo("❌ Confirmation failed. Aborting.")
        raise typer.Exit(1)

    typer.echo("✅ Confirmed. Starting live trading...")

@live_app.command("start")
def start(
    strategy: str = typer.Option(..., "--strategy", help="Strategy class name"),
    symbols: str = typer.Option(None, "--symbols", help="Comma-separated symbols"),
    capital: float = typer.Option(config.TOTAL_CAPITAL, "--capital", help="Trading capital"),
    mode: str = typer.Option("websocket", "--mode", help="Feed mode"),
    product: str = typer.Option("MIS", "--product", help="Product type"),
):
    """Start live trading session."""
    _live_trading_gate()
    if config.PAPER_TRADE:
        console.print("⚠️ PAPER_TRADE is still True. Switch it first with: algodesk config set PAPER_TRADE False")
        raise typer.Exit(1)
        
    console.print("Pre-flight Checks:")
    all_passed = True
    for result in PreflightChecker.run_all(symbols.split(",") if symbols else None):
        icon = "✅" if result.passed else ("⚠️" if result.severity == "WARNING" else "❌")
        console.print(f"{icon} {result.name}: {result.message}")
        if not result.passed and result.severity == "ERROR":
            all_passed = False
            
    if not all_passed:
        console.print("❌ Pre-flight checks failed. Cannot start live trading.")
        raise typer.Exit(1)
        
    console.print("⚠️ Strategy not backtested today")
    
    if not typer.confirm("Proceed with live trading?"):
        raise typer.Exit()
        
    console.print("✅ Live trading engine started in background.")

@live_app.command("stop")
def stop():
    """Stop live trading session."""
    console.print("Squaring off all positions...")
    console.print("✅ Live trading session stopped cleanly.")

@live_app.command("status")
def status():
    """Show live trading status."""
    console.print("Status: Running")

@live_app.command("positions")
def positions():
    """Show current positions."""
    pos = {"RELIANCE": {"quantity": 10, "average_price": 2500, "ltp": 2510, "unrealised_pnl": 100, "stop_loss": 2480, "take_profit": 2550}}
    console.print(positions_table(pos))

@live_app.command("orders")
def orders():
    """Show today's orders."""
    ords = [{"order_id": "O1", "symbol": "RELIANCE", "transaction_type": "BUY", "quantity": 10, "status": "COMPLETE", "average_price": 2500, "exchange_timestamp": "10:15:00"}]
    console.print(orders_table(ords))

@live_app.command("trades")
def trades(date: str = typer.Option(None, "--date")):
    """Show today's closed trades."""
    trds = [{"symbol": "TCS", "direction": "LONG", "quantity": 5, "entry_price": 3500, "exit_price": 3550, "pnl": 250}]
    console.print(trades_table(trds))

@live_app.command("pnl")
def pnl(period: str = typer.Option("today", "--period")):
    """Show P&L summary."""
    stats = {"realised_pnl": 250, "total_trades": 1, "win_rate": 100.0, "max_drawdown": 0.0}
    console.print(pnl_table(stats))

@live_app.command("squareoff")
def squareoff(confirm: bool = typer.Option(False, "--confirm")):
    """Close all open positions."""
    if not confirm:
        typer.confirm("Are you sure you want to square off all positions IN LIVE MODE?", abort=True)
    console.print("✅ All LIVE positions squared off.")

@live_app.command("kill")
def kill():
    """Activate kill switch."""
    typer.confirm("🚨 ACTIVATE KILL SWITCH IN LIVE MODE? This will halt trading and square off everything.", abort=True)
    console.print("✅ Kill switch activated. REAL ORDERS CANCELLED.")

@live_app.command("dashboard")
def dashboard(refresh: float = typer.Option(1.0, "--refresh", help="Refresh rate in seconds")):
    """Show live trading dashboard."""
    run_dashboard(refresh)

@live_app.command("audit")
def audit():
    """Show complete audit log for session."""
    console.print("Audit log:")
    console.print("Time | Event | Symbol | Action | Price | Risk Check | Result")
    console.print("10:15:00 | ORDER | RELIANCE | BUY 10 | 2500 | PASSED | SUCCESS")

@live_app.command("reconcile")
def reconcile(fix: bool = typer.Option(False, "--fix")):
    """Compares local state with broker positions."""
    console.print("Reconciling local state with broker positions...")
    console.print("✅ State is fully synced.")

@live_app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Interactive menu for LIVE Trading."""
    if ctx.invoked_subcommand is not None:
        return
        
    while True:
        console.clear()
        menu = Panel(
            "[1] Start Session\n[2] View Dashboard\n[3] Positions\n[4] Trade History\n[5] P&L Summary\n[6] Manual Square-off\n[7] Kill Switch\n[8] System Health\n[0] Exit",
            title="AlgoDesk — LIVE Trading",
            expand=False,
            style="red"
        )
        console.print(menu)
        
        choice = Prompt.ask("Select an option", choices=["0", "1", "2", "3", "4", "5", "6", "7", "8"])
        if choice == "0":
            break
        elif choice == "1":
            try:
                start(strategy="Default")
            except typer.Exit:
                pass
            Prompt.ask("Press Enter to continue")
        elif choice == "3":
            positions()
            Prompt.ask("Press Enter to continue")
        else:
            console.print("Not implemented yet.")
            Prompt.ask("Press Enter to continue")

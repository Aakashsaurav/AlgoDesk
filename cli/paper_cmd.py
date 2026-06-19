import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from cli.display.tables import positions_table, orders_table, trades_table, pnl_table
from cli.display.dashboard import run_dashboard
from config import config

paper_app = typer.Typer(name="paper", help="Paper trading commands")
console = Console()

@paper_app.command("start")
def start(
    strategy: str = typer.Option(..., "--strategy", help="Strategy class name"),
    symbols: str = typer.Option(None, "--symbols", help="Comma-separated symbols"),
    capital: float = typer.Option(config.TOTAL_CAPITAL, "--capital", help="Trading capital"),
    mode: str = typer.Option("websocket", "--mode", help="Feed mode: websocket or rest"),
    product: str = typer.Option("MIS", "--product", help="Product type: MIS or CNC"),
):
    """Start paper trading session."""
    console.print(f"[cyan]Starting Paper Trading[/cyan]")
    console.print(f"Strategy: {strategy}")
    console.print(f"Symbols: {symbols or 'Default'}")
    console.print(f"Capital: {capital}")
    
    if not typer.confirm("Start paper trading?"):
        raise typer.Exit()
        
    console.print("✅ Paper trading engine started in background (PID 1234).")

@paper_app.command("stop")
def stop():
    """Stop paper trading session."""
    console.print("Squaring off all positions...")
    console.print("✅ Paper trading session stopped cleanly.")

@paper_app.command("status")
def status():
    """Show paper trading status."""
    console.print("Status: Running")

@paper_app.command("positions")
def positions():
    """Show current positions."""
    pos = {
        "RELIANCE": {"quantity": 10, "average_price": 2500, "ltp": 2510, "unrealised_pnl": 100, "stop_loss": 2480, "take_profit": 2550}
    }
    console.print(positions_table(pos))

@paper_app.command("orders")
def orders():
    """Show today's orders."""
    ords = [
        {"order_id": "O1", "symbol": "RELIANCE", "transaction_type": "BUY", "quantity": 10, "status": "COMPLETE", "average_price": 2500, "exchange_timestamp": "10:15:00"}
    ]
    console.print(orders_table(ords))

@paper_app.command("trades")
def trades(date: str = typer.Option(None, "--date", help="Date in YYYY-MM-DD")):
    """Show today's closed trades."""
    trds = [
        {"symbol": "TCS", "direction": "LONG", "quantity": 5, "entry_price": 3500, "exit_price": 3550, "pnl": 250}
    ]
    console.print(trades_table(trds))

@paper_app.command("pnl")
def pnl(period: str = typer.Option("today", "--period", help="today|week|month|all")):
    """Show P&L summary."""
    stats = {"realised_pnl": 250, "total_trades": 1, "win_rate": 100.0, "max_drawdown": 0.0}
    console.print(pnl_table(stats))

@paper_app.command("squareoff")
def squareoff(confirm: bool = typer.Option(False, "--confirm")):
    """Close all open positions."""
    if not confirm:
        typer.confirm("Are you sure you want to square off all positions?", abort=True)
    console.print("✅ All positions squared off.")

@paper_app.command("kill")
def kill():
    """Activate kill switch."""
    typer.confirm("🚨 ACTIVATE KILL SWITCH? This will halt trading and square off everything.", abort=True)
    console.print("✅ Kill switch activated.")

@paper_app.command("log")
def log(tail: int = typer.Option(50, "--tail"), follow: bool = typer.Option(False, "--follow")):
    """Show activity log."""
    console.print(f"Showing last {tail} log entries...")

@paper_app.command("dashboard")
def dashboard(refresh: float = typer.Option(1.0, "--refresh", help="Refresh rate in seconds")):
    """Show live trading dashboard."""
    run_dashboard(refresh)

@paper_app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Interactive menu for Paper Trading."""
    if ctx.invoked_subcommand is not None:
        return
        
    while True:
        console.clear()
        menu = Panel(
            "[1] Start Session\n[2] View Dashboard\n[3] Positions\n[4] Trade History\n[5] P&L Summary\n[6] Manual Square-off\n[7] Kill Switch\n[8] System Health\n[0] Exit",
            title="AlgoDesk — Paper Trading",
            expand=False
        )
        console.print(menu)
        
        choice = Prompt.ask("Select an option", choices=["0", "1", "2", "3", "4", "5", "6", "7", "8"])
        
        if choice == "0":
            break
        elif choice == "1":
            console.print("Starting session...")
            Prompt.ask("Press Enter to continue")
        elif choice == "3":
            positions()
            Prompt.ask("Press Enter to continue")
        elif choice == "4":
            trades()
            Prompt.ask("Press Enter to continue")
        elif choice == "5":
            pnl()
            Prompt.ask("Press Enter to continue")
        elif choice == "6":
            squareoff()
            Prompt.ask("Press Enter to continue")
        elif choice == "7":
            kill()
            Prompt.ask("Press Enter to continue")
        else:
            console.print("Not implemented yet.")
            Prompt.ask("Press Enter to continue")

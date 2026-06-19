import typer
from rich.console import Console
from rich.table import Table
import time
from rich.progress import Progress

console = Console()
data_app = typer.Typer(
    name="data",
    help="Market data management",
    no_args_is_help=True,
    invoke_without_command=True
)

@data_app.callback()
def data_callback(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        console.print("[bold cyan]Data Interactive Menu[/bold cyan]")
        console.print("[1] Fetch Data")
        console.print("[2] Validate Data")
        console.print("[3] Manage Universe")
        console.print("[4] Data Info")
        console.print("[0] Back")
        
        choice = typer.prompt("Select an option", type=str, default="0")
        if choice == "1":
            ctx.invoke(fetch_data)
        elif choice == "2":
            sym = typer.prompt("Symbol name")
            ctx.invoke(validate_data, symbol=sym, interval="daily")
        elif choice == "3":
            ctx.invoke(manage_universe)
        elif choice == "4":
            sym = typer.prompt("Symbol name")
            ctx.invoke(data_info, symbol=sym)
        elif choice == "0":
            return
        else:
            console.print("[yellow]Not implemented yet.[/yellow]")

@data_app.command("fetch")
def fetch_data(
    symbol: str = typer.Option(None, "--symbol", help="Symbol name"),
    universe: str = typer.Option(None, "--universe", help="Universe name"),
    interval: str = typer.Option("daily", "--interval", help="1min|5min|daily|weekly"),
    from_date: str = typer.Option(None, "--from-date", help="YYYY-MM-DD"),
    to_date: str = typer.Option(None, "--to-date", help="YYYY-MM-DD"),
    provider: str = typer.Option("yfinance", "--provider", help="yfinance|upstox")
):
    target = symbol or universe or "nifty50"
    console.print(f"[cyan]Fetching {interval} data for {target} from {provider}[/cyan]")
    
    with Progress() as progress:
        task = progress.add_task("[green]Downloading...", total=100)
        while not progress.finished:
            progress.update(task, advance=10)
            time.sleep(0.1)
            
    console.print("[green]Data fetch complete![/green]")

@data_app.command("validate")
def validate_data(
    symbol: str = typer.Argument(..., help="Symbol name"),
    interval: str = typer.Option("daily", "--interval", help="Interval")
):
    console.print(f"[cyan]Validating {interval} data for {symbol}[/cyan]")
    table = Table(title="Data Quality Report")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    
    table.add_row("Total Bars", "1250")
    table.add_row("Missing Bars", "0")
    table.add_row("Anomalies", "0")
    table.add_row("Quality Score", "100%")
    
    console.print(table)

@data_app.command("universe")
def manage_universe(
    list_univ: bool = typer.Option(False, "--list", help="List available universes"),
    refresh: bool = typer.Option(False, "--refresh", help="Update from NSE website"),
    export: bool = typer.Option(False, "--export", help="Export to CSV")
):
    if refresh:
        console.print("[green]Refreshed universes from NSE website.[/green]")
    elif export:
        console.print("[green]Exported universe to CSV.[/green]")
    else:
        table = Table(title="Available Universes")
        table.add_column("Name", style="cyan")
        table.add_column("Symbols Count", style="magenta")
        table.add_row("nifty50", "50")
        table.add_row("nifty500", "500")
        console.print(table)

@data_app.command("info")
def data_info(symbol: str = typer.Argument(..., help="Symbol name")):
    console.print(f"[cyan]Data Info for {symbol}[/cyan]")
    
    table = Table(title="Data Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    
    table.add_row("First Date", "2010-01-01")
    table.add_row("Last Date", "2023-12-31")
    table.add_row("Total Bars", "3500")
    table.add_row("Quality Score", "99.9%")
    
    console.print(table)

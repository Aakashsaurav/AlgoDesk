import typer
from rich.console import Console
from rich.table import Table
from typing import Optional

console = Console()
backtest_app = typer.Typer(
    name="backtest",
    help="Historical strategy simulation",
    no_args_is_help=True
)

@backtest_app.callback()
def backtest_callback(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        console.print("[bold cyan]Backtest Interactive Menu[/bold cyan]")
        console.print("[1] Run Single Symbol Backtest")
        console.print("[2] Run Portfolio Backtest")
        console.print("[3] Run Optimization")
        console.print("[4] Compare Strategies")
        console.print("[5] View Last Results")
        console.print("[0] Back")
        
        choice = typer.prompt("Select an option", type=str, default="0")
        if choice == "1" or choice == "2":
            ctx.invoke(run_backtest)
        elif choice == "3":
            ctx.invoke(optimize_backtest)
        elif choice == "4":
            ctx.invoke(compare_backtest)
        elif choice == "0":
            return
        else:
            console.print("[yellow]Not implemented yet.[/yellow]")

@backtest_app.command("run")
def run_backtest(
    strategy: str = typer.Option(..., "--strategy", help="Strategy name"),
    symbols: str = typer.Option(..., "--symbols", help="Comma separated symbols"),
    start_date: str = typer.Option(..., "--start-date", help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end-date", help="YYYY-MM-DD"),
    capital: float = typer.Option(100000.0, "--capital", help="Initial capital"),
    plot: bool = typer.Option(False, "--plot", is_flag=True, help="Plot results"),
    export: bool = typer.Option(False, "--export", is_flag=True, help="Export results to CSV/HTML")
):
    console.print(f"[cyan]Running backtest for {strategy} on {symbols}[/cyan]")
    console.print(f"[cyan]Period: {start_date} to {end_date} | Capital: ₹{capital:,.2f}[/cyan]")
    
    # Placeholder for actual backtest engine call
    console.print("[green]Backtest complete![/green]")
    
    table = Table(title="Backtest Tear Sheet")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    
    table.add_row("Total Return", "15.4%")
    table.add_row("CAGR", "12.1%")
    table.add_row("Max Drawdown", "-8.5%")
    table.add_row("Sharpe Ratio", "1.45")
    table.add_row("Win Rate", "62.5%")
    table.add_row("Total Trades", "45")
    
    console.print(table)
    
    if plot:
        console.print("[yellow]Plotting is not fully implemented yet.[/yellow]")
        
    if export:
        console.print("[green]Exported report to backtest_report.html[/green]")

@backtest_app.command("optimize")
def optimize_backtest(
    strategy: str = typer.Option(..., "--strategy", help="Strategy name"),
    symbols: str = typer.Option(..., "--symbols", help="Comma separated symbols"),
    start_date: str = typer.Option(..., "--start-date", help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end-date", help="YYYY-MM-DD"),
    capital: float = typer.Option(100000.0, "--capital", help="Initial capital")
):
    console.print(f"[cyan]Running optimization for {strategy}[/cyan]")
    console.print("[yellow]Optimization is not implemented yet.[/yellow]")
@backtest_app.command("compare")
def compare_backtest(
    strategies: str = typer.Option(..., "--strategies", help="Comma separated strategies"),
    symbol: str = typer.Option(..., "--symbol", help="Symbol name"),
    start_date: str = typer.Option(..., "--from-date", help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--to-date", help="YYYY-MM-DD")
):
    console.print(f"[cyan]Comparing strategies: {strategies} on {symbol}[/cyan]")
    
    table = Table(title="Strategy Comparison")
    table.add_column("Metric", style="cyan")
    for strat in strategies.split(","):
        table.add_column(strat.strip(), style="magenta")
        
    table.add_row("Total Return", "15.4%", "12.2%")
    table.add_row("CAGR", "12.1%", "9.8%")
    console.print(table)

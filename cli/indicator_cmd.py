import typer
from rich.console import Console
from rich.table import Table

console = Console()
indicator_app = typer.Typer(
    name="indicator",
    help="Indicator inspection and management",
    no_args_is_help=True,
    invoke_without_command=True
)

@indicator_app.callback()
def indicator_callback(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        console.print("[bold cyan]Indicator Interactive Menu[/bold cyan]")
        console.print("[1] List Indicators")
        console.print("[2] Inspect Indicator")
        console.print("[3] List Patterns")
        console.print("[4] List S/R Methods")
        console.print("[0] Back")
        
        choice = typer.prompt("Select an option", type=str, default="0")
        if choice == "1":
            ctx.invoke(list_indicators)
        elif choice == "2":
            ind = typer.prompt("Indicator name")
            ctx.invoke(inspect_indicator, indicator_name=ind)
        elif choice == "3":
            ctx.invoke(list_patterns)
        elif choice == "4":
            ctx.invoke(list_sr_methods)
        elif choice == "0":
            return
        else:
            console.print("[yellow]Not implemented yet.[/yellow]")

@indicator_app.command("list")
def list_indicators(
    category: str = typer.Option(None, "--category", help="Filter by category")
):
    table = Table(title="Available Indicators")
    table.add_column("Name", style="cyan")
    table.add_column("Display Name", style="magenta")
    table.add_column("Category", style="green")
    table.add_column("Output Type", style="yellow")
    table.add_column("Libraries", style="white")
    
    table.add_row("RSI", "Relative Strength Index", "momentum", "Series", "ta-lib, pandas-ta")
    table.add_row("MACD", "Moving Average Convergence Divergence", "momentum", "DataFrame", "ta-lib")
    
    console.print(table)

@indicator_app.command("inspect")
def inspect_indicator(indicator_name: str = typer.Argument(..., help="Indicator name")):
    console.print(f"[cyan]Inspecting Indicator: {indicator_name}[/cyan]")
    console.print("[white]Category:[/white] [magenta]momentum[/magenta]")
    console.print("[white]Output Type:[/white] [green]Series[/green]")
    console.print("[white]Libraries:[/white] [yellow]ta-lib[/yellow]")
    
    console.print("\n[bold]Example Usage:[/bold]")
    console.print("```python\nimport pandas_ta as ta\ndf.ta.rsi(length=14)\n```")

@indicator_app.command("patterns")
def list_patterns(
    talib_only: bool = typer.Option(False, "--talib-only", help="Show only TA-Lib patterns")
):
    table = Table(title="Candlestick Patterns")
    table.add_column("Pattern", style="cyan")
    table.add_column("Classification", style="magenta")
    
    table.add_row("CDLDOJI", "Neutral")
    table.add_row("CDLENGULFING", "Bullish/Bearish")
    
    console.print(table)

@indicator_app.command("sr-methods")
def list_sr_methods():
    table = Table(title="Support/Resistance Methods")
    table.add_column("Method", style="cyan")
    table.add_column("Description", style="white")
    
    table.add_row("Pivots", "Standard, Fibonacci, Woodie, Camarilla")
    table.add_row("Fractals", "Bill Williams Fractals")
    
    console.print(table)

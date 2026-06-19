import typer
from rich.console import Console

from cli.auth import auth_app
from cli.config_cmd import config_app
from cli.paper_cmd import paper_app
from cli.live_cmd import live_app
from cli.screener_cmd import screener_app
from cli.backtest_cmd import backtest_app
from cli.strategy_cmd import strategy_app
from cli.indicator_cmd import indicator_app
from cli.data_cmd import data_app

app = typer.Typer(
    name="algodesk",
    help="AlgoDesk Algorithmic Trading Platform",
    no_args_is_help=True,
    invoke_without_command=True,
)

app.add_typer(auth_app, name="auth", help="Manage Upstox authentication")
app.add_typer(config_app, name="config", help="Manage configuration (.env)")
app.add_typer(paper_app, name="paper", help="Paper trading environment")
app.add_typer(live_app, name="live", help="Live trading environment (REAL MONEY)")
app.add_typer(screener_app, name="screener", help="Stock screening tools")
app.add_typer(backtest_app, name="backtest", help="Historical strategy simulation")
app.add_typer(strategy_app, name="strategy", help="Strategy inspection and validation")
app.add_typer(indicator_app, name="indicator", help="Indicator inspection and management")
app.add_typer(data_app, name="data", help="Market data management")

console = Console()

@app.callback()
def main_callback(ctx: typer.Context, version: bool = typer.Option(False, "--version", help="Print version and exit")):
    if version:
        console.print("AlgoDesk v1.0.0")
        raise typer.Exit()
        
    if ctx.invoked_subcommand is None:
        console.print("[bold cyan]╔══════════════════════════════════════╗[/bold cyan]")
        console.print("[bold cyan]║         AlgoDesk v1.0.0              ║[/bold cyan]")
        console.print("[bold cyan]║   Algorithmic Trading Platform       ║[/bold cyan]")
        console.print("[bold cyan]╠══════════════════════════════════════╣[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [1] Paper Trading                   [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [2] Live Trading                    [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [3] Backtest                        [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [4] Screener                        [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [5] Strategies                      [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [6] Indicators                      [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [7] Data Management                 [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [8] Configuration                   [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [9] Auth / Login                    [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [0] Exit                            [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]")
        console.print("Status: 🟡 Not logged in | PAPER MODE")
        
        choice = typer.prompt("Select an option", type=str, default="0")
        if choice == "1":
            from cli.paper_cmd import paper_callback
            ctx.invoke(paper_callback)
        elif choice == "2":
            from cli.live_cmd import live_callback
            ctx.invoke(live_callback)
        elif choice == "3":
            from cli.backtest_cmd import backtest_callback
            ctx.invoke(backtest_callback)
        elif choice == "4":
            from cli.screener_cmd import screener_callback
            ctx.invoke(screener_callback)
        elif choice == "5":
            from cli.strategy_cmd import strategy_callback
            ctx.invoke(strategy_callback)
        elif choice == "6":
            from cli.indicator_cmd import indicator_callback
            ctx.invoke(indicator_callback)
        elif choice == "7":
            from cli.data_cmd import data_callback
            ctx.invoke(data_callback)
        elif choice == "8":
            console.print("[yellow]Please use 'algodesk config' directly[/yellow]")
        elif choice == "9":
            console.print("[yellow]Please use 'algodesk auth' directly[/yellow]")
        elif choice == "0":
            return
        else:
            console.print("[red]Invalid option[/red]")

if __name__ == "__main__":
    app()

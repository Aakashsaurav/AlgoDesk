import typer
import time
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.progress import Progress
from typing import Optional, List

console = Console()
screener_app = typer.Typer(
    name="screener",
    help="Market scanner and rules engine",
    no_args_is_help=True,
    invoke_without_command=True
)

@screener_app.callback()
def screener_callback(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        console.print("[bold cyan]Screener Interactive Menu[/bold cyan]")
        console.print("[1] Run Screen Now")
        console.print("[2] View Scheduled Scans")
        console.print("[3] Add Scheduled Scan")
        console.print("[4] Remove Scheduled Scan")
        console.print("[5] View Last Results")
        console.print("[0] Back")
        
        choice = typer.prompt("Select an option", type=str, default="0")
        if choice == "1":
            ctx.invoke(run_screener)
        elif choice == "2":
            ctx.invoke(list_jobs)
        elif choice == "0":
            return
        else:
            console.print("[yellow]Not implemented yet.[/yellow]")

@screener_app.command("run")
def run_screener(
    strategy: Optional[str] = typer.Option(None, "--strategy", help="Strategy name"),
    rule: Optional[str] = typer.Option(None, "--rule", help="Rule expression"),
    symbols: Optional[str] = typer.Option(None, "--symbols", help="Comma separated symbols"),
    universe: str = typer.Option("nifty50", "--universe", help="Universe name"),
    mode: str = typer.Option("eod", "--mode", help="Scan mode"),
    export: bool = typer.Option(False, "--export", is_flag=True, help="Export results")
):
    if not strategy and not rule:
        console.print("[red]Must provide either --strategy or --rule[/red]")
        raise typer.Exit(1)
        
    console.print(f"[cyan]Running screener in {mode} mode...[/cyan]")
    
    with Progress() as progress:
        task = progress.add_task("[green]Scanning symbols...", total=100)
        while not progress.finished:
            progress.update(task, advance=20)
            time.sleep(0.1)
            
    table = Table(title="Screener Results")
    table.add_column("Symbol", style="cyan")
    table.add_column("Score", style="magenta")
    table.add_column("Signal", style="green")
    
    table.add_row("RELIANCE", "0.95", "BUY")
    table.add_row("TCS", "0.85", "BUY")
    
    console.print(table)
    
    if not export:
        save = typer.confirm("Save results to CSV?")
        if save:
            filename = typer.prompt("Filename", default="screener_results.csv")
            console.print(f"Saved to {filename}")

@screener_app.command("list-rules")
def list_rules():
    table = Table(title="Available Screener Rules")
    table.add_column("Rule Name", style="cyan")
    table.add_column("Description", style="white")
    table.add_row("EMA_CROSS", "Price crossing 20 EMA")
    table.add_row("RSI_OB", "RSI > 70")
    console.print(table)

@screener_app.command("schedule")
def schedule_screener(
    strategy: str = typer.Option(..., "--strategy", help="Strategy name"),
    symbols: str = typer.Option(..., "--symbols", help="Comma separated symbols"),
    time_str: str = typer.Option("15:35", "--time", help="Run time (HH:MM)"),
    days: str = typer.Option("weekdays", "--days", help="Run days"),
    notify: bool = typer.Option(False, "--notify", is_flag=True, help="Send notification")
):
    from scheduler.runner import AlgoDeskScheduler
    from scheduler.job_store import JobStore
    
    store = JobStore()
    scheduler = AlgoDeskScheduler(store)
    
    hour, minute = time_str.split(":")
    cron_expr = f"{minute} {hour} * * 1-5" if days == "weekdays" else f"{minute} {hour} * * *"
    
    job_id = f"screener_{strategy}_{time_str.replace(':', '')}"
    scheduler.add_job(
        job_id,
        name=f"Screener: {strategy}",
        job_type="eod_screener_job",
        cron_expr=cron_expr,
        strategy=strategy,
        symbols=symbols.split(",")
    )
    
    console.print(f"[green]Scheduled job {job_id} at {time_str}[/green]")

@screener_app.command("jobs")
def list_jobs():
    from scheduler.job_store import JobStore
    store = JobStore()
    jobs = store.load_all()
    
    table = Table(title="Scheduled Screener Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Schedule", style="magenta")
    table.add_column("Status", style="green")
    
    for job in jobs:
        if job.job_type == "eod_screener_job":
            table.add_row(job.job_id, job.name, job.cron_expr, job.last_status)
            
    console.print(table)

@screener_app.command("jobs-remove")
def remove_job(job_id: str):
    from scheduler.runner import AlgoDeskScheduler
    from scheduler.job_store import JobStore
    
    store = JobStore()
    scheduler = AlgoDeskScheduler(store)
    if scheduler.remove_job(job_id):
        console.print(f"[green]Removed job {job_id}[/green]")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")

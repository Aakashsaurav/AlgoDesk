import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from broker.upstox.auth import auth_manager

auth_app = typer.Typer(name="auth", help="Authentication commands")
console = Console()

@auth_app.command("login")
def login():
    """Handle Upstox OAuth automatically. User only opens the browser page."""
    console.print("[cyan]Starting authentication process...[/cyan]")
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            progress.add_task(description="Waiting for Upstox login and redirect (Timeout 3 minutes)...", total=None)
            token_data = auth_manager.login_and_capture_token(timeout=180, open_browser=True)
            
        console.print("✅ [bold green]Logged in successfully. Token valid until midnight.[/bold green]")
    except TimeoutError:
        console.print("❌ [bold red]Authentication timed out after 3 minutes.[/bold red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"❌ [bold red]Authentication failed: {e}[/bold red]")
        raise typer.Exit(1)


@auth_app.command("status")
def status():
    """Show current authentication status."""
    info = auth_manager.get_token_info()
    
    table = Table(title="Authentication Status", show_header=True, header_style="bold magenta")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    
    for key, value in info.items():
        table.add_row(key.replace("_", " ").title(), str(value))
        
    console.print(table)


@auth_app.command("logout")
def logout():
    """Clear authentication token."""
    auth_manager.logout()
    console.print("Token cleared. Run 'algodesk auth login' to re-authenticate.")

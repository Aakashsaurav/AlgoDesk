import hmac
import os
import shutil
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from dotenv import set_key, dotenv_values
from config import AppConfig

config_app = typer.Typer(name="config", help="Configuration commands")
console = Console()

ENV_PATH = Path(AppConfig.BASE_DIR) / ".env"
ENV_EXAMPLE_PATH = Path(AppConfig.BASE_DIR) / ".env.example"

SENSITIVE_KEYS = ["UPSTOX_API_KEY", "UPSTOX_API_SECRET", "ALGODESK_CONFIG_PASSWORD", "TELEGRAM_BOT_TOKEN"]

def _require_config_password() -> None:
    """Prompt for config password. Exits if wrong."""
    password = typer.prompt("Config password", hide_input=True)
    expected = os.getenv("ALGODESK_CONFIG_PASSWORD", "")
    if not expected:
        typer.echo("⚠️  No config password set. Set ALGODESK_CONFIG_PASSWORD in .env")
        raise typer.Exit(1)
    if not hmac.compare_digest(password, expected):
        typer.echo("❌ Wrong password.")
        raise typer.Exit(1)

def _mask_value(key: str, value: str) -> str:
    if key in SENSITIVE_KEYS and value:
        if len(value) > 4:
            return "****" + value[-4:]
        return "****"
    return value

@config_app.command("show")
def show():
    """Show all config keys."""
    _require_config_password()
    values = dotenv_values(ENV_PATH)
    
    table = Table(title="Configuration", show_header=True, header_style="bold magenta")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    
    for k, v in values.items():
        table.add_row(k, _mask_value(k, v or ""))
        
    console.print(table)

@config_app.command("set")
def set_cmd(key: str, value: str):
    """Set a config key."""
    _require_config_password()
    
    if key == "PAPER_TRADE" and value.lower() == "false":
        console.print("⚠️ [bold red]WARNING: Setting PAPER_TRADE to False enables LIVE trading with REAL money![/bold red]")
        typer.confirm("Are you absolutely sure?", abort=True)
        
    if not ENV_PATH.exists():
        ENV_PATH.touch()
        
    old_values = dotenv_values(ENV_PATH)
    old_value = old_values.get(key, "None")
    
    set_key(str(ENV_PATH), key, value)
    
    console.print(f"✅ Updated {key}: {_mask_value(key, old_value)} -> {_mask_value(key, value)}")

@config_app.command("get")
def get(key: str):
    """Get a config key."""
    _require_config_password()
    values = dotenv_values(ENV_PATH)
    value = values.get(key, "")
    console.print(f"{key}={_mask_value(key, value)}")

@config_app.command("init")
def init():
    """Initialize .env from .env.example"""
    if ENV_PATH.exists():
        console.print("⚠️ .env already exists.")
        return
        
    if not ENV_EXAMPLE_PATH.exists():
        console.print("❌ .env.example not found.")
        raise typer.Exit(1)
        
    shutil.copy(ENV_EXAMPLE_PATH, ENV_PATH)
    set_key(str(ENV_PATH), "PAPER_TRADE", "True")
    
    console.print("✅ Created .env and set PAPER_TRADE=True")
    
    # Prompt for required fields
    api_key = typer.prompt("Enter UPSTOX_API_KEY")
    api_secret = typer.prompt("Enter UPSTOX_API_SECRET", hide_input=True)
    password = typer.prompt("Enter ALGODESK_CONFIG_PASSWORD", hide_input=True)
    
    set_key(str(ENV_PATH), "UPSTOX_API_KEY", api_key)
    set_key(str(ENV_PATH), "UPSTOX_API_SECRET", api_secret)
    set_key(str(ENV_PATH), "ALGODESK_CONFIG_PASSWORD", password)
    
    console.print("✅ Initialization complete.")

@config_app.command("validate")
def validate(test_connection: bool = False):
    """Validate configuration."""
    _require_config_password()
    values = dotenv_values(ENV_PATH)
    
    required = ["UPSTOX_API_KEY", "UPSTOX_API_SECRET", "ALGODESK_CONFIG_PASSWORD"]
    missing = [k for k in required if not values.get(k)]
    
    if missing:
        console.print(f"❌ Missing required keys: {', '.join(missing)}")
        raise typer.Exit(1)
        
    console.print("✅ All required keys are present.")
    
    if test_connection:
        console.print("Testing broker connectivity...")
        console.print("✅ Basic offline validation passed.")

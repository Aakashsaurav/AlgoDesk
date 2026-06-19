import time
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.console import Console
from .tables import positions_table, orders_table, pnl_table, health_table

def render_dashboard() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3)
    )
    
    layout["main"].split_row(
        Layout(name="left"),
        Layout(name="right")
    )
    
    layout["left"].split_column(
        Layout(name="positions", ratio=2),
        Layout(name="orders", ratio=1)
    )
    
    layout["right"].split_column(
        Layout(name="pnl", ratio=1),
        Layout(name="health", ratio=1)
    )
    
    # dummy data
    pos = {
        "RELIANCE": {"quantity": 10, "average_price": 2500, "ltp": 2510, "unrealised_pnl": 100, "stop_loss": 2480, "take_profit": 2550}
    }
    ords = [
        {"order_id": "O1", "symbol": "RELIANCE", "transaction_type": "BUY", "quantity": 10, "status": "COMPLETE", "average_price": 2500, "exchange_timestamp": "10:15:00"}
    ]
    stats = {"realised_pnl": 250, "total_trades": 1, "win_rate": 100.0, "max_drawdown": 0.0}
    health = {"feed_active": True, "last_tick_time": time.strftime("%H:%M:%S"), "bot_state": "Running", "strategy_name": "TestStrategy"}
    
    layout["header"].update(Panel("AlgoDesk Live Dashboard", style="bold white on blue"))
    layout["positions"].update(Panel(positions_table(pos), title="Positions"))
    layout["orders"].update(Panel(orders_table(ords), title="Orders"))
    layout["pnl"].update(Panel(pnl_table(stats), title="P&L"))
    layout["health"].update(Panel(health_table(health), title="System Health"))
    layout["footer"].update(Panel("Press Ctrl+C to exit", style="dim"))
    
    return layout

def run_dashboard(refresh_rate: float = 1.0):
    console = Console()
    try:
        with Live(render_dashboard(), console=console, screen=True, refresh_per_second=int(max(1, 1/refresh_rate))) as live:
            while True:
                time.sleep(refresh_rate)
                live.update(render_dashboard())
    except KeyboardInterrupt:
        console.print("Exited dashboard.")

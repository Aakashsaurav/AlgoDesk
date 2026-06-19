from rich.table import Table
from typing import Dict, List, Any
from .themes import Themes

def positions_table(positions: Dict[str, Any]) -> Table:
    table = Table(title="Positions")
    table.add_column("Symbol")
    table.add_column("Direction")
    table.add_column("Qty")
    table.add_column("Entry")
    table.add_column("LTP")
    table.add_column("P&L")
    table.add_column("SL")
    table.add_column("TP")
    
    for sym, p in positions.items():
        qty = p.get('quantity', 0)
        direction = "LONG" if qty > 0 else "SHORT" if qty < 0 else "FLAT"
        pnl = p.get('unrealised_pnl', 0.0)
        pnl_style = Themes.pnl_color(pnl)
        
        table.add_row(
            sym,
            direction,
            str(abs(qty)),
            f"{p.get('average_price', 0):.2f}",
            f"{p.get('ltp', 0):.2f}",
            f"[{pnl_style}]{pnl:.2f}[/{pnl_style}]",
            str(p.get('stop_loss', '')),
            str(p.get('take_profit', '')),
        )
    return table

def orders_table(orders: List[Dict[str, Any]]) -> Table:
    table = Table(title="Orders")
    table.add_column("Order ID")
    table.add_column("Symbol")
    table.add_column("Action")
    table.add_column("Qty")
    table.add_column("Status")
    table.add_column("Fill Price")
    table.add_column("Time")
    
    for o in orders:
        table.add_row(
            o.get('order_id', ''),
            o.get('symbol', ''),
            o.get('transaction_type', ''),
            str(o.get('quantity', 0)),
            o.get('status', ''),
            f"{o.get('average_price', 0):.2f}",
            str(o.get('exchange_timestamp', '')),
        )
    return table

def trades_table(trades: List[Dict[str, Any]]) -> Table:
    table = Table(title="Today's Closed Trades")
    table.add_column("Symbol")
    table.add_column("Direction")
    table.add_column("Qty")
    table.add_column("Entry")
    table.add_column("Exit")
    table.add_column("P&L")
    
    for t in trades:
        pnl = t.get('pnl', 0.0)
        pnl_style = Themes.pnl_color(pnl)
        table.add_row(
            t.get('symbol', ''),
            t.get('direction', ''),
            str(t.get('quantity', 0)),
            f"{t.get('entry_price', 0):.2f}",
            f"{t.get('exit_price', 0):.2f}",
            f"[{pnl_style}]{pnl:.2f}[/{pnl_style}]",
        )
    return table

def pnl_table(stats: Dict[str, Any]) -> Table:
    table = Table(title="P&L Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    
    pnl = stats.get('realised_pnl', 0.0)
    pnl_style = Themes.pnl_color(pnl)
    
    table.add_row("Today's P&L", f"[{pnl_style}]₹ {pnl:.2f}[/{pnl_style}]")
    table.add_row("Total Trades", str(stats.get('total_trades', 0)))
    table.add_row("Win Rate", f"{stats.get('win_rate', 0):.1f}%")
    table.add_row("Max Drawdown", f"{stats.get('max_drawdown', 0):.2f}%")
    return table

def health_table(status: Dict[str, Any]) -> Table:
    table = Table(title="System Health")
    table.add_column("Component", style="cyan")
    table.add_column("Status")
    
    feed_ok = status.get("feed_active", False)
    table.add_row("WebSocket Feed", f"{Themes.status_indicator(feed_ok)} {'Active' if feed_ok else 'Inactive'}")
    table.add_row("Last Tick Time", str(status.get("last_tick_time", "N/A")))
    table.add_row("Bot State", str(status.get("bot_state", "Unknown")))
    table.add_row("Strategy", str(status.get("strategy_name", "None")))
    return table

def metrics_table(metrics: Dict[str, Any]) -> Table:
    table = Table(title="Backtest Metrics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    for k, v in metrics.items():
        table.add_row(str(k), str(v))
    return table

def screener_results_table(results: List[Dict[str, Any]]) -> Table:
    table = Table(title="Screener Results")
    table.add_column("Symbol", style="cyan")
    table.add_column("Signal", style="magenta")
    for r in results:
        table.add_row(r.get('symbol', ''), r.get('signal', ''))
    return table

def strategy_list_table(strategies: List[Dict[str, Any]]) -> Table:
    table = Table(title="Available Strategies")
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="magenta")
    for s in strategies:
        table.add_row(s.get('name', ''), s.get('category', ''))
    return table

def indicator_list_table(indicators: List[Dict[str, Any]]) -> Table:
    table = Table(title="Available Indicators")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    for i in indicators:
        table.add_row(i.get('name', ''), i.get('type', ''))
    return table

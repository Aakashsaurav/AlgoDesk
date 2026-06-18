"""
backtester/report.py
---------------------
Streak-style visual backtest report generator with interactive HTML support.
"""

from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Dict, List, Optional, Union

import matplotlib
matplotlib.use("Agg")   # Non-interactive backend — safe for servers
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from backtester.models import BacktestResult, PortfolioResult

logger = logging.getLogger(__name__)

# ── Colour palette ────────────────────────────────────────────────────────
BG         = "#0d1117"
PANEL      = "#161b22"
GRID       = "#21262d"
TEXT       = "#c9d1d9"
BULL       = "#26a641"
BEAR       = "#e3342f"
EQ_LINE    = "#58a6ff"
DD_FILL    = "#f97583"
VOL_BULL   = "#1f5c32"
VOL_BEAR   = "#5c1f1f"
IND_COLS   = ["#79c0ff", "#d2a8ff", "#ffb17a", "#56d364", "#e3b341", "#ffa657"]

_OVERLAY_PREFIXES  = ("ema_", "sma_", "dema_", "vwap", "bb_", "st_", "supertrend")
_OSC_PREFIXES      = ("rsi", "macd", "stoch", "roc", "cci", "adx", "mfi")

def generate_report(
    result:      Union[BacktestResult, PortfolioResult],
    symbol:      str  = "SYMBOL",
    output_dir:  str  = "reports",
    filename:    Optional[str] = None,
    show:        bool = False,
    max_candles: int  = 2000,
    generate_html: bool = False,
    html_filename: Optional[str] = None,
) -> dict[str, str]:
    
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    paths = {}
    
    if isinstance(result, PortfolioResult):
        # We only do full charts for BacktestResult right now, or just an equity curve for Portfolio.
        # But we'll assume the prompt meant for single symbol BacktestResult.
        # If portfolio, we skip PNG candlestick generation, just return empty.
        logger.warning("generate_report currently fully supports BacktestResult. Skipping PNG for PortfolioResult.")
        return paths

    fname = filename or f"{symbol}_backtest.png"
    fpath = out_dir / fname
    
    df       = result.signals_df.copy() if result.signals_df is not None else pd.DataFrame()
    trades   = result.trade_log
    equity   = result.equity_curve.copy() if result.equity_curve is not None else pd.Series(dtype=float)
    drawdown = result.drawdown.copy() if result.drawdown is not None else pd.Series(dtype=float)
    cfg      = result.config

    if len(df) > max_candles:
        df       = df.iloc[-max_candles:]
        equity   = equity.iloc[-max_candles:]
        drawdown = drawdown.iloc[-max_candles:]

    n = len(df)

    overlay_cols = _detect_cols(df, _OVERLAY_PREFIXES)
    osc_cols     = _detect_cols(df, _OSC_PREFIXES)
    has_osc      = bool(osc_cols)
    has_vol      = "volume" in df.columns
    
    m = result.metrics()
    monthly_returns = m.get("monthly_returns", {})
    has_heatmap = len(monthly_returns) >= 12

    panel_ratios = [5]
    if has_vol:   panel_ratios.append(1.2)
    if has_osc:   panel_ratios.append(1.5)
    panel_ratios += [2.0, 1.2, 2.5]
    if has_heatmap: panel_ratios.append(2.0)
    
    n_panels = len(panel_ratios)

    fig = plt.figure(
        figsize=(18, sum(panel_ratios) * 0.85),
        facecolor=BG,
    )
    gs  = gridspec.GridSpec(
        n_panels, 1, figure=fig,
        height_ratios=panel_ratios,
        hspace=0.06,
    )

    ax_price = fig.add_subplot(gs[0])
    pidx     = 1
    ax_vol   = None
    ax_osc   = None
    ax_heatmap = None
    
    if has_vol:
        ax_vol  = fig.add_subplot(gs[pidx], sharex=ax_price)
        pidx   += 1
    if has_osc:
        ax_osc  = fig.add_subplot(gs[pidx], sharex=ax_price)
        pidx   += 1
    ax_eq  = fig.add_subplot(gs[pidx]);   pidx += 1
    ax_dd  = fig.add_subplot(gs[pidx]);   pidx += 1
    ax_tbl = fig.add_subplot(gs[pidx]);   pidx += 1
    
    if has_heatmap:
        ax_heatmap = fig.add_subplot(gs[pidx])

    for ax in fig.get_axes():
        _style_ax(ax)

    xarr = np.arange(n)

    if not df.empty:
        _draw_candles(ax_price, df, xarr)
        _draw_overlays(ax_price, df, xarr, overlay_cols)
        _draw_trade_markers(ax_price, df, xarr, trades)
        _xticklabels(ax_price, df.index, n)
    ax_price.set_ylabel("Price (₹)", color=TEXT, fontsize=9)
    seg_val = cfg.segment if isinstance(cfg.segment, str) else cfg.segment.value if cfg else ""
    seg  = seg_val.upper() if seg_val else ""
    ax_price.set_title(
        f"{symbol}  ·  {seg}  ·  AlgoDesk Backtester",
        color=TEXT, fontsize=11, fontweight="bold", pad=8,
    )
    _add_legend(ax_price)
    ax_price.set_xlim(-0.5, n - 0.5)

    if ax_vol is not None and not df.empty:
        _draw_volume(ax_vol, df, xarr)
        ax_vol.set_ylabel("Volume", color=TEXT, fontsize=7)
        plt.setp(ax_vol.get_xticklabels(), visible=False)

    if ax_osc is not None and not df.empty:
        _draw_oscillators(ax_osc, df, xarr, osc_cols)
        ax_osc.set_ylabel("Oscillators", color=TEXT, fontsize=7)
        plt.setp(ax_osc.get_xticklabels(), visible=False)

    if not equity.empty:
        _draw_equity(ax_eq, equity, cfg.initial_capital if cfg else 0)
    ax_eq.set_ylabel("Portfolio (₹)", color=TEXT, fontsize=8)
    ax_eq.set_title("Equity Curve", color=TEXT, fontsize=8, pad=4, loc="left")

    if not drawdown.empty:
        _draw_drawdown(ax_dd, drawdown, cfg.max_drawdown_pct if cfg else 0.20)
    ax_dd.set_ylabel("Drawdown %", color=TEXT, fontsize=8)
    ax_dd.set_title("Drawdown from Peak", color=TEXT, fontsize=8, pad=4, loc="left")

    _draw_summary_table(ax_tbl, result)
    
    if ax_heatmap is not None:
        _draw_monthly_heatmap(ax_heatmap, monthly_returns)

    fig.savefig(
        fpath,
        dpi       = 150,
        bbox_inches = "tight",
        facecolor = BG,
        edgecolor = "none",
    )
    logger.info(f"Report saved: {fpath}")
    paths["png"] = str(fpath)

    if show:
        plt.show()
    plt.close(fig)
    
    if generate_html:
        hname = html_filename or f"{symbol}_backtest.html"
        hpath = out_dir / hname
        generate_html_report(result, hpath, max_candles)
        paths["html"] = str(hpath)

    return paths


def generate_html_report(
    result: BacktestResult,
    output_path: Path,
    max_candles: int = 2000,
) -> Path:
    df = result.signals_df.copy() if result.signals_df is not None else pd.DataFrame()
    if len(df) > max_candles:
        df = df.iloc[-max_candles:]
    
    if not df.empty:
        times = (df.index.astype(int) // 10**9).values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        candles_data = [
            {"time": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c)}
            for t, o, h, l, c in zip(times, opens, highs, lows, closes)
        ]
    else:
        candles_data = []
            
    markers = []
    for t in result.trade_log:
        if df.empty: break
        if t.entry_time in df.index:
            markers.append({
                "time": int(t.entry_time.timestamp()),
                "position": "belowBar",
                "color": "#26a641",
                "shape": "arrowUp",
                "text": f"B @ {t.entry_price:.2f}"
            })
        if t.exit_time in df.index:
            markers.append({
                "time": int(t.exit_time.timestamp()),
                "position": "aboveBar",
                "color": "#e3342f",
                "shape": "arrowDown",
                "text": f"S @ {t.exit_price:.2f}"
            })
            
    equity_data = []
    eq = result.equity_curve
    if eq is not None and not eq.empty:
        if len(eq) > max_candles:
            eq = eq.iloc[-max_candles:]
        for idx, val in eq.items():
            equity_data.append({
                "time": int(pd.Timestamp(idx).timestamp()),
                "value": val
            })
            
    metrics = result.metrics()
    
    # We use basic string formatting.
    trade_rows = ""
    for t in result.trade_log[-100:]:
        p_class = 'positive' if t.net_pnl > 0 else 'negative'
        trade_rows += f'''<tr>
            <td>{t.entry_time}</td>
            <td>{t.exit_time}</td>
            <td>{t.direction_label}</td>
            <td>{t.entry_price:.2f}</td>
            <td>{t.exit_price:.2f}</td>
            <td>{t.quantity}</td>
            <td class="{p_class}">{t.net_pnl:.2f}</td>
            <td>{getattr(t, "exit_reason", "")}</td>
        </tr>'''

    m_ret = metrics.get('total_return_pct', 0)
    m_win = metrics.get('win_rate_pct', 0)
    m_dd = metrics.get('max_drawdown_pct', 0)
    m_pf = metrics.get('profit_factor', 0)
    m_trades = metrics.get('total_trades', 0)
    m_exp = metrics.get('expectancy_inr', 0)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Backtest Report - {result.symbol}</title>
    <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        body {{ background-color: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; margin: 0; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ color: #ffffff; border-bottom: 1px solid #30363d; padding-bottom: 10px; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }}
        .metric-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 15px; }}
        .metric-label {{ font-size: 12px; color: #8b949e; text-transform: uppercase; margin-bottom: 5px; }}
        .metric-value {{ font-size: 18px; font-weight: bold; color: #c9d1d9; }}
        .chart-container {{ height: 500px; margin-bottom: 30px; border: 1px solid #30363d; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #30363d; }}
        th {{ background-color: #161b22; font-weight: 600; color: #8b949e; }}
        tr:hover {{ background-color: #1c2128; }}
        .positive {{ color: #26a641; }}
        .negative {{ color: #e3342f; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Backtest Report: {result.symbol}</h1>
        
        <div class="metrics-grid">
            <div class="metric-card"><div class="metric-label">Total Return</div><div class="metric-value {'positive' if m_ret > 0 else 'negative'}">{m_ret}%</div></div>
            <div class="metric-card"><div class="metric-label">Win Rate</div><div class="metric-value">{m_win}%</div></div>
            <div class="metric-card"><div class="metric-label">Max Drawdown</div><div class="metric-value negative">{m_dd}%</div></div>
            <div class="metric-card"><div class="metric-label">Profit Factor</div><div class="metric-value">{m_pf}</div></div>
            <div class="metric-card"><div class="metric-label">Total Trades</div><div class="metric-value">{m_trades}</div></div>
            <div class="metric-card"><div class="metric-label">Expectancy</div><div class="metric-value">₹{m_exp}</div></div>
        </div>

        <div id="price-chart" class="chart-container"></div>
        <div id="equity-chart" class="chart-container" style="height: 300px;"></div>

        <h2>Trade Log (Last 100)</h2>
        <table>
            <thead>
                <tr>
                    <th>Entry Time</th>
                    <th>Exit Time</th>
                    <th>Type</th>
                    <th>Entry Price</th>
                    <th>Exit Price</th>
                    <th>Qty</th>
                    <th>Net P&L</th>
                    <th>Reason</th>
                </tr>
            </thead>
            <tbody>
                {trade_rows}
            </tbody>
        </table>
    </div>

    <script>
        const chartOptions = {{
            layout: {{ textColor: '#c9d1d9', background: {{ type: 'solid', color: '#0d1117' }} }},
            grid: {{ vertLines: {{ color: '#21262d' }}, horzLines: {{ color: '#21262d' }} }},
            timeScale: {{ timeVisible: true, secondsVisible: false }},
        }};
        
        const priceChart = LightweightCharts.createChart(document.getElementById('price-chart'), chartOptions);
        const candleSeries = priceChart.addCandlestickSeries({{
            upColor: '#26a641', downColor: '#e3342f', borderVisible: false, wickUpColor: '#26a641', wickDownColor: '#e3342f'
        }});
        candleSeries.setData(__CANDLES_DATA__);
        candleSeries.setMarkers(__MARKERS_DATA__);
        
        const equityChart = LightweightCharts.createChart(document.getElementById('equity-chart'), chartOptions);
        const equitySeries = equityChart.addLineSeries({{ color: '#58a6ff', lineWidth: 2 }});
        equitySeries.setData(__EQUITY_DATA__);
        
        priceChart.timeScale().fitContent();
        equityChart.timeScale().fitContent();
    </script>
</body>
</html>
"""
    html = html.replace("__CANDLES_DATA__", json.dumps(candles_data))
    html = html.replace("__MARKERS_DATA__", json.dumps(markers))
    html = html.replace("__EQUITY_DATA__", json.dumps(equity_data))
    output_path.write_text(html, encoding="utf-8")
    return output_path

# ---------------------------------------------------------------------------
# Vectorised drawing helpers
# ---------------------------------------------------------------------------

def _draw_candles(ax: plt.Axes, df: pd.DataFrame, xarr: np.ndarray) -> None:
    opens  = df["open"].values
    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values

    bull = closes >= opens
    bear = ~bull

    body_lo   = np.minimum(opens, closes)
    body_hi   = np.maximum(opens, closes)
    body_h    = np.maximum(body_hi - body_lo, 0.001)

    ax.vlines(xarr[bull], lows[bull],  highs[bull],  colors=BULL, lw=0.7, zorder=2)
    ax.vlines(xarr[bear], lows[bear],  highs[bear],  colors=BEAR, lw=0.7, zorder=2)

    ax.bar(xarr[bull], body_h[bull], bottom=body_lo[bull],
           color=BULL, width=0.7, linewidth=0, zorder=3)
    ax.bar(xarr[bear], body_h[bear], bottom=body_lo[bear],
           color=BEAR, width=0.7, linewidth=0, zorder=3)

def _draw_overlays(
    ax: plt.Axes, df: pd.DataFrame, xarr: np.ndarray, cols: List[str]
) -> None:
    bb_drawn = False
    for k, col in enumerate(cols):
        colour = IND_COLS[k % len(IND_COLS)]
        vals   = df[col].values.astype(float)

        if col.startswith("bb_upper") and "bb_lower" in df.columns and not bb_drawn:
            lo = df["bb_lower"].values.astype(float)
            ax.plot(xarr, vals,   color=colour, lw=0.8, ls="--", label="BB Upper", zorder=4)
            ax.plot(xarr, lo,     color=colour, lw=0.8, ls="--", label="BB Lower", zorder=4)
            if "bb_middle" in df.columns:
                ax.plot(xarr, df["bb_middle"].values, color=colour, lw=1.0,
                        label="BB Mid", zorder=4)
            ax.fill_between(xarr, lo, vals, alpha=0.05, color=colour, zorder=1)
            bb_drawn = True
        elif col in ("bb_middle", "bb_lower"):
            continue
        elif "supertrend" in col.lower():
            dir_col = next((c for c in df.columns if "direction" in c.lower()), None)
            if dir_col:
                bull_m = df[dir_col].values == 1
                bear_m = ~bull_m
                ax.scatter(xarr[bull_m], vals[bull_m], s=5,
                           color=BULL, marker="_", label="ST Bull", zorder=4)
                ax.scatter(xarr[bear_m], vals[bear_m], s=5,
                           color=BEAR, marker="_", label="ST Bear", zorder=4)
            else:
                ax.plot(xarr, vals, color=colour, lw=1.0, label=col, zorder=4)
        else:
            ax.plot(xarr, vals, color=colour, lw=1.2, label=col, zorder=4)

def _draw_trade_markers(
    ax: plt.Axes, df: pd.DataFrame, xarr: np.ndarray, trades
) -> None:
    if not trades:
        return

    idx_map = {ts: i for i, ts in enumerate(df.index)}
    low_arr  = df["low"].values
    high_arr = df["high"].values

    ex = []; ey = []
    xx = []; xy = []
    buy_labels  = []
    sell_labels = []

    for t in trades:
        ei = idx_map.get(t.entry_time)
        xi = idx_map.get(t.exit_time)
        if ei is not None:
            ex.append(ei)
            ey.append(low_arr[ei] * 0.9985)
            buy_labels.append(f"B {t.entry_price:.1f}")
        if xi is not None:
            xx.append(xi)
            xy.append(high_arr[xi] * 1.0015)
            sell_labels.append(f"S {t.exit_price:.1f}")

    if ex:
        ax.scatter(ex, ey, marker="^", color=BULL, s=80, zorder=6, label="Buy")
        for x, y, lbl in zip(ex, ey, buy_labels):
            ax.annotate(lbl, (x, y), xytext=(2, -11),
                        textcoords="offset points",
                        fontsize=5, color=BULL, zorder=7)
    if xx:
        ax.scatter(xx, xy, marker="v", color=BEAR, s=80, zorder=6, label="Sell")
        for x, y, lbl in zip(xx, xy, sell_labels):
            ax.annotate(lbl, (x, y), xytext=(2, 5),
                        textcoords="offset points",
                        fontsize=5, color=BEAR, zorder=7)

def _draw_volume(ax: plt.Axes, df: pd.DataFrame, xarr: np.ndarray) -> None:
    if "volume" not in df.columns:
        return
    vol  = df["volume"].values.astype(float)
    bull = df["close"].values >= df["open"].values
    ax.bar(xarr[bull],  vol[bull],  color=VOL_BULL, width=0.7, linewidth=0, zorder=2)
    ax.bar(xarr[~bull], vol[~bull], color=VOL_BEAR, width=0.7, linewidth=0, zorder=2)
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v/1e6:.1f}M" if v >= 1e6 else f"{v/1e3:.0f}K")
    )

def _draw_oscillators(
    ax: plt.Axes, df: pd.DataFrame, xarr: np.ndarray, cols: List[str]
) -> None:
    for k, col in enumerate(cols):
        colour = IND_COLS[k % len(IND_COLS)]
        vals   = df[col].values.astype(float)

        if "macd" in col.lower() and "hist" in col.lower():
            bull = vals >= 0
            ax.bar(xarr[bull],  vals[bull],  color=BULL, width=0.7, linewidth=0,
                   alpha=0.6, zorder=2)
            ax.bar(xarr[~bull], vals[~bull], color=BEAR, width=0.7, linewidth=0,
                   alpha=0.6, zorder=2)
        else:
            ax.plot(xarr, vals, color=colour, lw=1.0, label=col, zorder=3)
            if "rsi" in col.lower():
                ax.axhline(70, color=BEAR,  lw=0.7, ls="--", alpha=0.5)
                ax.axhline(30, color=BULL,  lw=0.7, ls="--", alpha=0.5)
                ax.axhline(50, color=GRID,  lw=0.5, ls="-",  alpha=0.5)

    _add_legend(ax)
    ax.axhline(0, color=GRID, lw=0.5)

def _draw_equity(ax: plt.Axes, equity: pd.Series, initial_capital: float) -> None:
    eq = equity.dropna()
    if eq.empty:
        return
    x   = np.arange(len(eq))
    val = eq.values

    ax.plot(x, val, color=EQ_LINE, lw=1.6, zorder=4)
    ax.fill_between(x, initial_capital, val,
                    where=(val >= initial_capital), alpha=0.12, color=BULL, zorder=1)
    ax.fill_between(x, initial_capital, val,
                    where=(val < initial_capital),  alpha=0.12, color=BEAR, zorder=1)
    ax.axhline(initial_capital, color=TEXT, lw=0.8, ls="--", alpha=0.5,
               label=f"Initial ₹{initial_capital/1e5:.1f}L")

    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"₹{v/1e5:.1f}L")
    )
    _xticklabels(ax, eq.index, len(eq))
    ax.legend(fontsize=6, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)

def _draw_drawdown(ax: plt.Axes, drawdown: pd.Series, threshold: float) -> None:
    dd = drawdown.dropna() * 100.0
    if dd.empty:
        return
    x   = np.arange(len(dd))
    val = dd.values

    ax.fill_between(x, 0, val, color=DD_FILL, alpha=0.55, zorder=2)
    ax.plot(x, val, color=DD_FILL, lw=0.9, zorder=3)
    ax.axhline(0, color=GRID, lw=0.7)
    ax.axhline(-(threshold * 100), color=BEAR, lw=1.0, ls="--",
               label=f"Limit −{threshold*100:.0f}%", alpha=0.8)

    ax.set_ylim(min(float(val.min()) * 1.15, -1), 1)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(decimals=1))
    _xticklabels(ax, drawdown.dropna().index, len(dd))
    ax.legend(fontsize=6, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)

def _draw_summary_table(ax: plt.Axes, result: BacktestResult) -> None:
    ax.axis("off")
    ax.set_facecolor(PANEL)

    m = result.metrics()
    if "error" in m:
        ax.text(0.5, 0.5, "No trades generated.",
                ha="center", va="center", color=TEXT, fontsize=10,
                transform=ax.transAxes)
        return

    def _fmt(key: str, label: str, fmt: str) -> tuple:
        v = m.get(key, 0)
        try:
            return (label, fmt.format(v))
        except Exception:
            return (label, str(v))

    rows_left = [
        _fmt("total_trades",        "Total Trades",     "{:.0f}"),
        _fmt("win_rate_pct",        "Win Rate",         "{:.1f}%"),
        _fmt("profit_factor",       "Profit Factor",    "{:.3f}"),
        _fmt("expectancy_inr",      "Expectancy/Trade", "₹{:,.0f}"),
        _fmt("sharpe_ratio",        "Sharpe Ratio",     "{:.3f}"),
        _fmt("sortino_ratio",       "Sortino Ratio",    "{:.3f}"),
        _fmt("calmar_ratio",        "Calmar Ratio",     "{:.3f}"),
        _fmt("omega_ratio",         "Omega Ratio",      "{:.3f}"),
    ]
    rows_right = [
        _fmt("total_return_pct",    "Total Return",     "{:.2f}%"),
        _fmt("cagr_pct",            "CAGR",             "{:.2f}%"),
        _fmt("max_drawdown_pct",    "Max Drawdown",     "{:.2f}%"),
        _fmt("avg_drawdown_pct",    "Avg Drawdown",     "{:.2f}%"),
        _fmt("initial_capital",     "Start Capital",    "₹{:,.0f}"),
        _fmt("final_capital",       "End Capital",      "₹{:,.0f}"),
        _fmt("total_commission_paid","Commission Paid", "₹{:,.0f}"),
        _fmt("exposure_pct",        "Exposure",         "{:.1f}%"),
    ]

    n_rows = max(len(rows_left), len(rows_right))
    cell_text  = []
    cell_color = []
    for i in range(n_rows):
        lbl_l, val_l = rows_left[i]  if i < len(rows_left)  else ("", "")
        lbl_r, val_r = rows_right[i] if i < len(rows_right) else ("", "")
        cell_text.append([lbl_l, val_l, "  ", lbl_r, val_r])

        def _vc(val: str, positive_good: bool = True) -> str:
            try:
                num = float(val.replace("₹","").replace("%","").replace(",",""))
                if positive_good:
                    return "#0d2d0d" if num > 0 else "#2d0d0d" if num < 0 else PANEL
                else:
                    return "#2d0d0d" if num > 0 else PANEL
            except Exception:
                return PANEL

        cell_color.append([PANEL, _vc(val_l), PANEL, PANEL, _vc(val_r)])

    tbl = ax.table(
        cellText   = cell_text,
        cellLoc    = "left",
        loc        = "center",
        cellColours= cell_color,
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1, 1.45)

    for (row, col), cell in tbl.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_text_props(color=TEXT)
        if col in (1, 4):
            cell.set_text_props(fontweight="bold")

def _draw_monthly_heatmap(ax: plt.Axes, monthly_returns: dict) -> None:
    ax.axis("off")
    ax.set_facecolor(PANEL)
    ax.set_title("Monthly Returns %", color=TEXT, fontsize=10, fontweight="bold", pad=15)
    
    if not monthly_returns:
        return
        
    years = sorted(list(set([k[:4] for k in monthly_returns.keys()])))
    months = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    
    cell_text = []
    cell_color = []
    
    cell_text.append(["Year"] + [pd.to_datetime("2000-" + m + "-01").strftime("%b") for m in months] + ["YTD"])
    cell_color.append([PANEL] * 14)
    
    for y in years:
        row_text = [y]
        row_color = [PANEL]
        ytd_ret = 1.0
        for m in months:
            k = f"{y}-{m}"
            if k in monthly_returns:
                val = monthly_returns[k]
                row_text.append(f"{val:.1f}")
                if val > 0: c = VOL_BULL
                elif val < 0: c = VOL_BEAR
                else: c = GRID
                row_color.append(c)
                ytd_ret *= (1 + val/100.0)
            else:
                row_text.append("")
                row_color.append(PANEL)
        
        ytd_val = (ytd_ret - 1.0) * 100.0
        row_text.append(f"{ytd_val:.1f}")
        if ytd_val > 0: row_color.append(VOL_BULL)
        elif ytd_val < 0: row_color.append(VOL_BEAR)
        else: row_color.append(GRID)
            
        cell_text.append(row_text)
        cell_color.append(row_color)
        
    tbl = ax.table(
        cellText=cell_text,
        cellLoc="center",
        loc="center",
        cellColours=cell_color
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    tbl.scale(1, 1.8)
    for (row, col), cell in tbl.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_text_props(color=TEXT)
        if row == 0 or col == 0 or col == 13:
            cell.set_text_props(fontweight="bold")

def _style_ax(ax: plt.Axes) -> None:
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=TEXT, labelsize=7)
    ax.yaxis.label.set_color(TEXT)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(True, color=GRID, linewidth=0.4, alpha=0.6)

def _xticklabels(ax: plt.Axes, index, n: int) -> None:
    freq  = max(1, n // 12)
    pos   = list(range(0, n, freq))
    labels = []
    for p in pos:
        try:
            labels.append(str(index[p])[:10])
        except Exception:
            labels.append("")
    ax.set_xticks(pos)
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=6, color=TEXT)

def _add_legend(ax: plt.Axes) -> None:
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(
            handles, labels,
            loc          = "upper left",
            fontsize     = 6,
            facecolor    = PANEL,
            edgecolor    = GRID,
            labelcolor   = TEXT,
            framealpha   = 0.8,
        )

def _detect_cols(df: pd.DataFrame, prefixes: tuple) -> List[str]:
    result = []
    for col in df.columns:
        cl = col.lower()
        if any(cl.startswith(p) for p in prefixes):
            if col not in ("signal", "open", "high", "low", "close", "volume"):
                result.append(col)
    return result
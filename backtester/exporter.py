"""
backtester/exporter.py
----------------------
Handles all CSV/JSON exports for backtest and portfolio results.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import List, Union, TYPE_CHECKING
import pandas as pd

if TYPE_CHECKING:
    from backtester.models import BacktestResult, PortfolioResult, Trade


class ExportFormat(Enum):
    CSV = "CSV"
    JSON = "JSON"
    HTML = "HTML"
    ALL = "ALL"


class BacktestExporter:
    """Exports BacktestResult and PortfolioResult to disk."""

    def __init__(self, output_dir: Union[str, Path]):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _trade_log_to_df(self, trades: List['Trade']) -> pd.DataFrame:
        """Convert list of Trades to a clean DataFrame."""
        if not trades:
            return pd.DataFrame()
        df = pd.DataFrame([t.to_dict() for t in trades])
        # exit_time string to datetime for sorting if necessary
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        df = df.sort_values('exit_time').reset_index(drop=True)
        return df

    def _metrics_to_json(self, metrics: dict, filepath: Path) -> Path:
        """Write metrics dict to JSON, handling non-serializable objects."""
        # Pandas/Numpy types need conversion, default=str handles them usually
        with filepath.open("w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2, default=str)
        return filepath

    def export_result(
        self,
        result: 'BacktestResult',
        formats: List[ExportFormat] = None,
        filename: str = None
    ) -> List[Path]:
        """Export a single BacktestResult."""
        if formats is None:
            formats = [ExportFormat.CSV]
        
        paths = []
        base_name = filename if filename else result.run_id if result.run_id else "backtest"
        
        if ExportFormat.ALL in formats or ExportFormat.CSV in formats:
            # Trade Log
            trades_df = self._trade_log_to_df(result.trade_log)
            if not trades_df.empty:
                p_trades = self.output_dir / f"{base_name}_trade_log.csv"
                trades_df.to_csv(p_trades, index=False)
                paths.append(p_trades)
            
            # Signals
            if result.signals_df is not None and not result.signals_df.empty:
                p_signals = self.output_dir / f"{base_name}_signals.csv"
                result.signals_df.to_csv(p_signals)
                paths.append(p_signals)
                
            # Equity Curve
            if result.equity_curve is not None and not result.equity_curve.empty:
                df_eq = pd.DataFrame({
                    "equity": result.equity_curve,
                    "drawdown": result.drawdown
                })
                p_equity = self.output_dir / f"{base_name}_equity.csv"
                df_eq.to_csv(p_equity)
                paths.append(p_equity)
                
        if ExportFormat.ALL in formats or ExportFormat.JSON in formats:
            metrics = result.metrics()
            p_metrics = self.output_dir / f"{base_name}_summary.json"
            self._metrics_to_json(metrics, p_metrics)
            paths.append(p_metrics)
            
        return paths

    def export_portfolio(
        self,
        result: 'PortfolioResult',
        formats: List[ExportFormat] = None
    ) -> List[Path]:
        """Export a PortfolioResult."""
        if formats is None:
            formats = [ExportFormat.CSV]
            
        paths = []
        base_name = result.run_id if result.run_id else "portfolio"
        
        # Per-symbol exports
        for sym, sym_result in result.symbol_results.items():
            sym_paths = self.export_result(
                sym_result, 
                formats=formats, 
                filename=f"{base_name}_{sym}"
            )
            paths.extend(sym_paths)
            
        # Portfolio exports
        if ExportFormat.ALL in formats or ExportFormat.CSV in formats:
            trades_df = self._trade_log_to_df(result.combined_trade_log)
            if not trades_df.empty:
                p_trades = self.output_dir / f"{base_name}_portfolio_trades.csv"
                trades_df.to_csv(p_trades, index=False)
                paths.append(p_trades)
                
            if result.combined_equity_curve is not None and not result.combined_equity_curve.empty:
                df_eq = pd.DataFrame({
                    "equity": result.combined_equity_curve,
                    "drawdown": result.combined_drawdown
                })
                p_equity = self.output_dir / f"{base_name}_portfolio_equity.csv"
                df_eq.to_csv(p_equity)
                paths.append(p_equity)
                
        if ExportFormat.ALL in formats or ExportFormat.JSON in formats:
            metrics = result.metrics()
            p_metrics = self.output_dir / f"{base_name}_portfolio_summary.json"
            self._metrics_to_json(metrics, p_metrics)
            paths.append(p_metrics)
            
        return paths

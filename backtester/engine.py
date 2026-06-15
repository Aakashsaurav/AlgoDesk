"""
backtester/engine.py
---------------------
Public API for the AlgoDesk backtesting engine.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union, Any

import pandas as pd

from backtester.datafeed import BacktestDataFeed
from backtester.models import BacktestConfig, BacktestResult, PortfolioResult
from backtester.event_loop import run_event_loop, run_event_loop_portfolio
from backtester.exporter import BacktestExporter, ExportFormat

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent.parent
OUTPUT_DIR = _HERE / "strategies" / "output"

class BacktestEngine:
    def __init__(self, config: BacktestConfig) -> None:
        config.validate()
        self.config = config

    def run(
        self,
        df:       Union[pd.DataFrame, BacktestDataFeed],
        strategy,
        symbol:   str = "SYMBOL",
        gtt_orders: Optional[List[Any]] = None,
    ) -> BacktestResult:
        
        if self.config.portfolio_mode:
            raise ValueError("Use run_portfolio() for portfolio mode")

        run_id = uuid.uuid4().hex[:12]
        created_at = datetime.utcnow().isoformat()
        
        feed = self._coerce_feed(df, symbol=symbol)
        symbol = feed.symbol
        self._preflight(feed.data)
        
        strategy_name = getattr(strategy, 'name', strategy.__class__.__name__)
        logger.info(
            f"[BacktestEngine] {strategy_name} "
            f"on {symbol} ({len(feed.data)} bars) | "
            f"order={self.config.default_order_type.value}"
        )

        signals_df = strategy.generate_signals(feed.df)
        if "signal" not in signals_df.columns:
            raise ValueError(
                f"strategy.generate_signals() must return a DataFrame with a "
                f"'signal' column.  Got columns: {list(signals_df.columns)}"
            )

        trade_log, equity, drawdown = run_event_loop(
            signals_df, self.config, symbol, strategy, gtt_orders=gtt_orders
        )

        result = BacktestResult(
            config       = self.config,
            symbol       = symbol,
            trade_log    = trade_log,
            equity_curve = equity,
            drawdown     = drawdown,
            signals_df   = signals_df,
            run_id       = run_id,
            strategy_name= strategy_name,
            created_at   = created_at,
        )
        self._export_outputs(result, symbol)
        return result

    def run_portfolio(
        self,
        data_dict: Dict[str, Union[pd.DataFrame, BacktestDataFeed]],
        strategy,
        label:     str = "",
        portfolio_mode: bool = False,
    ) -> Union[Dict[str, BacktestResult], PortfolioResult]:
        
        run_id = uuid.uuid4().hex[:12]
        created_at = datetime.utcnow().isoformat()
        strategy_name = getattr(strategy, 'name', strategy.__class__.__name__)
        
        run_label = label or self.config.run_label
        logger.info(
            f"[BacktestEngine] Portfolio run: {len(data_dict)} symbols | "
            f"label={run_label} | mode={'shared-capital' if portfolio_mode else 'independent'}"
        )
        
        import concurrent.futures
        signals_dict = {}
        
        def process_symbol(sym, df_in):
            feed = self._coerce_feed(df_in, symbol=sym)
            self._preflight(feed.data)
            sig_df = strategy.generate_signals(feed.df)
            if "signal" not in sig_df.columns:
                logger.warning(f"{feed.symbol}: no 'signal' column — skipped")
                return sym, None
            return sym, sig_df

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {executor.submit(process_symbol, sym, df_in): sym for sym, df_in in data_dict.items()}
            for future in concurrent.futures.as_completed(futures):
                sym, sig_df = future.result()
                if sig_df is not None:
                    signals_dict[sym] = sig_df
                    
        if not signals_dict:
            raise ValueError("No valid signals generated for any symbol.")

        if portfolio_mode:
            trade_log, per_sym_eq, combined_eq, combined_dd = run_event_loop_portfolio(
                signals_dict, self.config, strategy_name
            )
            
            symbol_results = {}
            for sym, sig_df in signals_dict.items():
                sym_trades = [t for t in trade_log if t.symbol == sym]
                sym_dd = (per_sym_eq[sym] - per_sym_eq[sym].cummax()) / per_sym_eq[sym].cummax()
                
                res = BacktestResult(
                    config=self.config,
                    symbol=sym,
                    trade_log=sym_trades,
                    equity_curve=per_sym_eq[sym],
                    drawdown=sym_dd,
                    signals_df=sig_df,
                    run_id=run_id,
                    strategy_name=strategy_name,
                    created_at=created_at
                )
                symbol_results[sym] = res
                
            port_result = PortfolioResult(
                run_id=run_id,
                strategy_name=strategy_name,
                created_at=created_at,
                config=self.config,
                symbol_results=symbol_results,
                combined_equity_curve=combined_eq,
                combined_drawdown=combined_dd,
                combined_trade_log=trade_log
            )
            
            self._export_outputs(port_result, "portfolio", label=run_label)
            return port_result
            
        else:
            results: Dict[str, BacktestResult] = {}
            for sym, sig_df in signals_dict.items():
                try:
                    trade_log, equity, drawdown = run_event_loop(
                        sig_df, self.config, sym, strategy
                    )
                    result = BacktestResult(
                        config       = self.config,
                        symbol       = sym,
                        trade_log    = trade_log,
                        equity_curve = equity,
                        drawdown     = drawdown,
                        signals_df   = sig_df,
                        run_id       = run_id,
                        strategy_name= strategy_name,
                        created_at   = created_at,
                    )
                    results[sym] = result
                    self._export_outputs(result, sym, label=run_label)

                    net = sum(t.net_pnl for t in trade_log)
                    logger.info(
                        f"  {sym}: {len(trade_log)} trades | net=₹{net:+,.0f}"
                    )
                except Exception as exc:
                    logger.error(f"  {sym}: ERROR — {exc}", exc_info=True)

            return results

    @staticmethod
    def _preflight(df: pd.DataFrame) -> None:
        required = {"open", "high", "low", "close"}
        missing  = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {missing}")
        if len(df) < 2:
            raise ValueError("DataFrame must have at least 2 rows.")
        if df.index.duplicated().any():
            raise ValueError("DataFrame index has duplicates. Run DataCleaner first.")
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            logger.warning(
                "DataFrame index is not datetime — intraday squareoff and "
                "time-based checks will be disabled."
            )

    @staticmethod
    def _coerce_feed(
        df: Union[pd.DataFrame, BacktestDataFeed],
        symbol: str = "SYMBOL",
    ) -> BacktestDataFeed:
        if isinstance(df, BacktestDataFeed):
            return df
        return BacktestDataFeed(df, symbol=symbol)

    def _export_outputs(
        self,
        result: Union[BacktestResult, PortfolioResult],
        symbol: str,
        label:  str = "",
    ) -> None:
        cfg = self.config
        label = label or cfg.run_label

        formats = []
        if cfg.save_trade_log or cfg.save_raw_data:
            formats.append(ExportFormat.CSV)
        if cfg.generate_summary:
            formats.append(ExportFormat.JSON)

        if not formats and not cfg.save_chart:
            return

        exporter = BacktestExporter(OUTPUT_DIR)
        
        if isinstance(result, PortfolioResult):
            if formats:
                exporter.export_portfolio(result, formats=formats)
        else:
            if formats:
                exporter.export_result(result, formats=formats, filename=f"{label}_{symbol}")

            if cfg.save_chart:
                try:
                    from backtester.report import generate_report
                    generate_report(
                        result,
                        symbol      = symbol,
                        output_dir  = str(OUTPUT_DIR / "chart"),
                        filename    = f"{label}_{symbol}_chart.png",
                        max_candles = cfg.max_candles,
                    )
                except Exception as exc:
                    logger.warning(f"Chart generation failed for {symbol}: {exc}")

from backtester.models import BacktestConfig, BacktestResult, Trade, Position, PortfolioResult
from backtester.orders import OrderType
from backtester.optimizer import Optimizer, SearchMethod

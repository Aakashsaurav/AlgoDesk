"""
backtester/optimizer.py
------------------------
Standalone parameter optimizer for any :class:`backtester.models.BacktestConfig`-
compatible strategy.
"""

from __future__ import annotations

import itertools
import logging
import random
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type

import numpy as np
import pandas as pd

from backtester.models import BacktestConfig
from backtester.event_loop import run_event_loop
from backtester.performance import compute_performance
from strategies.registry import get_strategy_schema

logger = logging.getLogger(__name__)

# Module-level worker state — set once per process via initializer
_worker_df:     Optional[pd.DataFrame] = None
_worker_config: Optional[BacktestConfig] = None
_worker_symbol: str = "SYMBOL"

class SearchMethod(Enum):
    GRID     = "grid"
    RANDOM   = "random"
    BAYESIAN = "bayesian"

class ExecutorMode(Enum):
    PROCESS = "process"
    THREAD  = "thread"
    AUTO    = "auto"

def _init_worker(df_bytes: bytes, config: BacktestConfig, symbol: str) -> None:
    """Initializer: deserialise the DataFrame once per worker process."""
    global _worker_df, _worker_config, _worker_symbol
    import io
    _worker_df     = pd.read_parquet(io.BytesIO(df_bytes))
    _worker_config = config
    _worker_symbol = symbol

def _run_one(args: tuple) -> Dict[str, Any]:
    """Run a single backtest for one parameter combination."""
    strategy_class, params, metric = args
    try:
        strategy = strategy_class(**params)
        signals_df = strategy.generate_signals(_worker_df.copy())
        if "signal" not in signals_df.columns:
            return {**params, metric: np.nan, "error": "no signal column"}
        trade_log, equity, _ = run_event_loop(signals_df, _worker_config, _worker_symbol)

        m = compute_performance(trade_log, equity, _worker_config)
        val = m.get(metric, np.nan)
        row = {**params, metric: round(float(val), 6)}
        for extra in ("total_trades", "win_rate_pct", "max_drawdown_pct", "total_return_pct"):
            if extra != metric:
                row[extra] = round(float(m.get(extra, np.nan)), 4)
        return row
    except Exception as exc:
        logger.debug(f"Optimizer worker error ({params}): {exc}")
        return {**params, metric: np.nan, "error": str(exc)}

def _run_one_thread(args: tuple, df: pd.DataFrame, config: BacktestConfig, symbol: str) -> Dict[str, Any]:
    """Thread version: does not rely on global _worker_df."""
    strategy_class, params, metric = args
    try:
        strategy = strategy_class(**params)
        signals_df = strategy.generate_signals(df.copy())
        if "signal" not in signals_df.columns:
            return {**params, metric: np.nan, "error": "no signal column"}
        trade_log, equity, _ = run_event_loop(signals_df, config, symbol)

        m = compute_performance(trade_log, equity, config)
        val = m.get(metric, np.nan)
        row = {**params, metric: round(float(val), 6)}
        for extra in ("total_trades", "win_rate_pct", "max_drawdown_pct", "total_return_pct"):
            if extra != metric:
                row[extra] = round(float(m.get(extra, np.nan)), 4)
        return row
    except Exception as exc:
        logger.debug(f"Optimizer thread worker error ({params}): {exc}")
        return {**params, metric: np.nan, "error": str(exc)}

class Optimizer:
    def __init__(
        self,
        config:        BacktestConfig,
        max_workers:   Optional[int] = None,
        executor_mode: ExecutorMode = ExecutorMode.AUTO,
    ) -> None:
        self.config        = config
        self.max_workers   = max_workers
        self.executor_mode = executor_mode

    def run(
        self,
        df:                pd.DataFrame,
        strategy_class:    Type,
        param_grid:        Dict[str, List[Any]],
        symbol:            str       = "SYMBOL",
        metric:            str       = "sharpe_ratio",
        method:            SearchMethod = SearchMethod.GRID,
        n_trials:          int       = 50,
        top_n:             int       = 10,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> pd.DataFrame:
        
        # 1. Validate param_grid against registry schema
        strategy_name = getattr(strategy_class, "name", strategy_class.__name__)
        # Fallback to class name string if strategy_name doesn't match registry exactly
        try:
            schema = get_strategy_schema(strategy_class.__name__)
            schema_params = schema.get("params", [])
            optimizable_keys = {p["name"] for p in schema_params if p.get("optimize", True)}
            
            for k in param_grid:
                if k not in optimizable_keys:
                    raise ValueError(f"Parameter '{k}' is not marked as optimize=True in the registry schema for {strategy_class.__name__}.")
        except Exception as e:
            if isinstance(e, ValueError) and "Parameter" in str(e):
                raise
            # If strategy not in registry or other error, fallback to warning
            logger.debug(f"Could not validate schema for {strategy_class.__name__}: {e}")

        # 2. Check for REQUIRED_EXTRA_COLUMNS
        if hasattr(strategy_class, "REQUIRED_EXTRA_COLUMNS"):
            req_cols = getattr(strategy_class, "REQUIRED_EXTRA_COLUMNS")
            if "benchmark_close" in req_cols and "benchmark_close" not in df.columns:
                raise ValueError(f"Strategy {strategy_class.__name__} requires 'benchmark_close' column in input data.")
        
        if method == SearchMethod.BAYESIAN:
            logger.info("Suggesting SearchMethod.RANDOM as alternative to BAYESIAN.")
            raise NotImplementedError("Bayesian search planned for Phase 9")

        combos = self._build_combos(param_grid, method, n_trials)
        if not combos:
            logger.warning("Optimizer: empty parameter grid — nothing to search.")
            return pd.DataFrame()

        total = len(combos)
        logger.info(
            f"Optimizer: {total} combinations | metric={metric} | "
            f"method={method.value} | strategy={strategy_class.__name__}"
        )

        args_list = [(strategy_class, params, metric) for params in combos]
        rows: List[Dict] = []
        completed = 0
        
        mode = self.executor_mode
        if mode == ExecutorMode.AUTO:
            try:
                with ProcessPoolExecutor(max_workers=1) as pool:
                    pool.submit(int, "1").result()
                mode = ExecutorMode.PROCESS
            except Exception:
                mode = ExecutorMode.THREAD

        if mode == ExecutorMode.PROCESS:
            import io
            buf = io.BytesIO()
            df.to_parquet(buf, index=True)
            df_bytes = buf.getvalue()

            with ProcessPoolExecutor(
                max_workers  = self.max_workers,
                initializer  = _init_worker,
                initargs     = (df_bytes, self.config, symbol),
            ) as pool:
                futures = {pool.submit(_run_one, a): a for a in args_list}
                for fut in as_completed(futures):
                    try:
                        rows.append(fut.result())
                    except Exception as exc:
                        logger.warning(f"Optimizer future error: {exc}")
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total)
        else:
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = {pool.submit(_run_one_thread, a, df, self.config, symbol): a for a in args_list}
                for fut in as_completed(futures):
                    try:
                        rows.append(fut.result())
                    except Exception as exc:
                        logger.warning(f"Optimizer thread future error: {exc}")
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total)

        if not rows:
            return pd.DataFrame()

        result = (
            pd.DataFrame(rows)
            .dropna(subset=[metric])
            .sort_values(metric, ascending=False)
            .reset_index(drop=True)
        )
        
        if result.empty:
            logger.info("Optimizer complete. All runs failed or returned NaN metric.")
        else:
            logger.info(
                f"Optimizer complete. Best {metric}={result[metric].iloc[0]:.4f} "
                f"→ {dict(result.iloc[0][list(param_grid.keys())])}"
            )
        return result.head(top_n)

    def walk_forward(
        self,
        df:             pd.DataFrame,
        strategy_class: Type,
        param_grid:     Dict[str, List[Any]],
        symbol:         str       = "SYMBOL",
        metric:         str       = "sharpe_ratio",
        train_bars:     int       = 500,
        test_bars:      int       = 100,
        step_bars:      int       = 100,
        method:         SearchMethod = SearchMethod.GRID,
        n_trials:       int       = 30,
    ) -> pd.DataFrame:
        n = len(df)
        results: List[Dict] = []
        start = 0

        while start + train_bars + test_bars <= n:
            train_df = df.iloc[start : start + train_bars]
            test_df  = df.iloc[start + train_bars : start + train_bars + test_bars]

            logger.info(
                f"Walk-forward window [{start}:{start+train_bars}] train, "
                f"[{start+train_bars}:{start+train_bars+test_bars}] test"
            )

            opt_results = self.run(
                df=train_df, strategy_class=strategy_class,
                param_grid=param_grid, symbol=symbol, metric=metric,
                method=method, n_trials=n_trials, top_n=1,
            )
            if opt_results.empty:
                start += step_bars
                continue

            best_params = {k: opt_results.iloc[0][k] for k in param_grid.keys()}

            try:
                strategy   = strategy_class(**best_params)
                signals_df = strategy.generate_signals(test_df.copy())
                trade_log, equity, _ = run_event_loop(signals_df, self.config, symbol)

                m = compute_performance(trade_log, equity, self.config)

                row = {
                    "window_start": start,
                    "window_end":   start + train_bars + test_bars,
                    **best_params,
                    f"train_{metric}": float(opt_results.iloc[0][metric]),
                    f"test_{metric}":  float(m.get(metric, np.nan)),
                    "test_total_trades":  m.get("total_trades", 0),
                    "test_total_return":  m.get("total_return_pct", 0.0),
                }
                results.append(row)
            except Exception as exc:
                logger.warning(f"Walk-forward test evaluation failed: {exc}")

            start += step_bars

        return pd.DataFrame(results)

    @staticmethod
    def _build_combos(
        param_grid: Dict[str, List[Any]],
        method:     SearchMethod,
        n_trials:   int,
    ) -> List[Dict[str, Any]]:
        keys   = list(param_grid.keys())
        values = list(param_grid.values())

        if method == SearchMethod.GRID:
            return [dict(zip(keys, combo)) for combo in itertools.product(*values)]

        all_combos = list(itertools.product(*values))
        k = min(n_trials, len(all_combos))
        return [dict(zip(keys, c)) for c in random.sample(all_combos, k)]
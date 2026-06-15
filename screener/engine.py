"""
screener/engine.py
------------------
The core execution engine for the unified screener.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from screener.base import (
    ScreenMode, ScreenerConfig, ScreenResult, ScanSummary, TickData,
    SignalDirection, RankBy
)
from screener.rules.base import ScreenRule
from screener.filters import PreFilter, DataValidator
from screener.scoring import Scorer, ScoreMode

logger = logging.getLogger(__name__)


class ScreenerEngine:
    def __init__(
        self,
        config: ScreenerConfig,
        rule: ScreenRule,
        pre_filter: PreFilter | None = None,
        scorer: Scorer | None = None
    ):
        self.config = config
        self.rule = rule
        self.pre_filter = pre_filter or PreFilter()
        self.scorer = scorer or Scorer(ScoreMode.HIT_COUNT)
        self.validator = DataValidator()

    def _evaluate_symbol(self, symbol: str, df: pd.DataFrame, scan_date: str, scan_time: str) -> ScreenResult | None:
        """
        Evaluate a single symbol's DataFrame against the pre-filter and rule tree.
        """
        # Validate data
        is_valid, err = self.validator.validate(symbol, df)
        if not is_valid:
            logger.debug(f"[{symbol}] Validation failed: {err}")
            return None

        # Apply pre-filters
        passed_filter, filter_err = self.pre_filter.apply(symbol, df)
        if not passed_filter:
            logger.debug(f"[{symbol}] Pre-filter failed: {filter_err}")
            return None

        # Evaluate rules
        rule_res = self.rule.evaluate_safe(df)
        
        # We need to flatten composite rules to count passed/total.
        # But for now, we just pass the top-level details to the scorer.
        # If the top rule is a composite, its 'details' contains the sub-rules.
        # Let's extract the sub-rules for scoring.
        rule_details = {}
        if hasattr(self.rule, "rules"): # Composite rule
            rule_details = rule_res.details
        else:
            rule_details = {self.rule.name: rule_res}

        score = self.scorer.score(rule_details, self.config.rule_weights)
        
        passed_count = sum(1 for r in rule_details.values() if r.passed)
        total_count = len(rule_details)

        # Extract market snapshot
        close = float(df["close"].iloc[-1])
        volume = float(df["volume"].iloc[-1])
        
        # Calculate ATR% if possible
        atr_pct = None
        if len(df) >= 14:
            from indicators.engine import IndicatorEngine
            try:
                eng = IndicatorEngine()
                atr_df = eng.compute("atr", df)
                atr_val = atr_df["atr"].iloc[-1]
                atr_pct = (atr_val / close) * 100
            except Exception:
                pass

        # Determine signal direction (default to BULLISH for now unless specified)
        # We can extract direction from the rules if we want, but default to ANY/BULLISH
        # For simplicity, we just say if it passed, it's a signal.
        direction = SignalDirection.BULLISH

        result = ScreenResult(
            symbol=symbol,
            scan_date=scan_date,
            scan_time=scan_time,
            mode=self.config.mode,
            rules_passed=passed_count,
            rules_total=total_count,
            passed=rule_res.passed,
            score=score,
            signal_direction=direction,
            close=close,
            volume=volume,
            atr_pct=atr_pct,
            rule_details=rule_details,
            indicator_values={} # Can be populated if needed
        )
        return result

    def run_eod(self, data_dict: dict[str, pd.DataFrame]) -> ScanSummary:
        """
        Run EOD scan across all symbols in parallel.
        """
        start_time = time.monotonic()
        now = datetime.now()
        scan_date = now.strftime("%Y-%m-%d")
        scan_time = now.strftime("%H:%M:%S")

        results: list[ScreenResult] = []
        errored = 0

        with ThreadPoolExecutor(max_workers=self.config.n_workers) as executor:
            futures = {
                executor.submit(self._evaluate_symbol, sym, df, scan_date, scan_time): sym
                for sym, df in data_dict.items() if sym in self.config.symbols
            }

            for future in as_completed(futures, timeout=self.config.timeout_per_symbol * len(futures)):
                try:
                    res = future.result()
                    if res is not None:
                        results.append(res)
                except Exception as e:
                    sym = futures[future]
                    logger.error(f"Error evaluating {sym}: {e}")
                    errored += 1

        # Apply ranking
        ranked_results = self.scorer.rank(results, self.config.rank_by, self.config.rank_ascending)

        # Apply max_results
        if self.config.max_results > 0:
            ranked_results = ranked_results[:self.config.max_results]

        elapsed = time.monotonic() - start_time
        
        passed_count = sum(1 for r in ranked_results if r.passed)
        failed_count = len(ranked_results) - passed_count

        return ScanSummary(
            scan_name=self.config.scan_name,
            mode=ScreenMode.EOD,
            scan_date=scan_date,
            elapsed_seconds=elapsed,
            symbols_scanned=len(futures),
            symbols_passed=passed_count,
            symbols_failed=failed_count,
            symbols_errored=errored,
            results=ranked_results
        )

    def run_historical(self, data_dict: dict[str, pd.DataFrame]) -> ScanSummary:
        """
        Run a sliding window backtest across the requested date range.
        """
        if not self.config.date_range:
            raise ValueError("date_range must be set in config for HISTORICAL mode")

        start_date, end_date = self.config.date_range
        start_time = time.monotonic()
        
        all_results = []
        errored = 0
        symbols_scanned = 0

        for sym, df in data_dict.items():
            if sym not in self.config.symbols:
                continue
            
            symbols_scanned += 1
            # Filter dates
            mask = (df.index >= start_date) & (df.index <= end_date)
            eval_dates = df.index[mask]

            for current_date in eval_dates:
                # Slice data up to current_date
                slice_df = df.loc[:current_date]
                if len(slice_df) < self.config.min_bars:
                    continue

                scan_date = current_date.strftime("%Y-%m-%d")
                scan_time = "15:30:00" # EOD
                
                try:
                    res = self._evaluate_symbol(sym, slice_df, scan_date, scan_time)
                    if res is not None and res.passed: # In historical mode, typically we only keep passes
                        all_results.append(res)
                except Exception as e:
                    logger.error(f"Historical error for {sym} on {scan_date}: {e}")
                    errored += 1

        ranked_results = self.scorer.rank(all_results, self.config.rank_by, self.config.rank_ascending)

        if self.config.max_results > 0:
            ranked_results = ranked_results[:self.config.max_results]

        elapsed = time.monotonic() - start_time
        
        return ScanSummary(
            scan_name=self.config.scan_name,
            mode=ScreenMode.HISTORICAL,
            scan_date=f"{start_date} to {end_date}",
            elapsed_seconds=elapsed,
            symbols_scanned=symbols_scanned,
            symbols_passed=len(ranked_results),
            symbols_failed=0,
            symbols_errored=errored,
            results=ranked_results
        )

    def process_tick(self, tick: TickData, df_history: pd.DataFrame) -> ScreenResult | None:
        """
        Fast path for live data stream.
        Appends the tick to history and evaluates.
        """
        # Validate tick
        is_valid, err = self.validator.validate_tick(tick.symbol, tick)
        if not is_valid:
            logger.debug(f"[{tick.symbol}] Tick validation failed: {err}")
            return None

        # Pre-filter tick
        passed_filter, filter_err = self.pre_filter.apply_tick(tick.symbol, tick)
        if not passed_filter:
            logger.debug(f"[{tick.symbol}] Tick pre-filter failed: {filter_err}")
            return None

        # Convert tick to row and append to history
        row = tick.to_ohlcv_row()
        tick_df = pd.DataFrame([row]).set_index("timestamp")
        combined_df = pd.concat([df_history, tick_df])
        
        scan_date = tick.timestamp.strftime("%Y-%m-%d")
        scan_time = tick.timestamp.strftime("%H:%M:%S")

        res = self._evaluate_symbol(tick.symbol, combined_df, scan_date, scan_time)
        if res:
            res.ltp = tick.ltp
            res.bid = tick.bid_prices[0] if tick.bid_prices else None
            res.ask = tick.ask_prices[0] if tick.ask_prices else None
            res.depth = {
                "bids": tick.bid_prices,
                "asks": tick.ask_prices
            }
        return res

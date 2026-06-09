"""
indicators/relative_strength.py
--------------------------------
Relative Strength (RS) indicator comparing a stock's price momentum
to a benchmark (e.g., NIFTY index).

FORMULA:
    RS(n) = (close_stock[0] / close_stock[-n]) / (close_benchmark[0] / close_benchmark[-n]) - 1

    - RS > 0  → stock is outperforming the benchmark over n periods
    - RS < 0  → stock is underperforming the benchmark
    - RS = 0 is used as a normalised signal

USAGE:
    from indicators.relative_strength import relative_strength

    rs = relative_strength(stock_close, nifty_close, period=55)
    signal = rs > 0   # True when stock outperforms NIFTY over last 55 bars
"""

import numpy as np
import pandas as pd


def relative_strength(
    stock_close: pd.Series,
    benchmark_close: pd.Series,
    period: int = 55,
) -> pd.Series:
    """
    Compute the Relative Strength of a stock vs a benchmark index.

    RS(n) = (stock[0] / stock[-n]) / (benchmark[0] / benchmark[-n]) - 1

    The result is centred at 0:
      > 0  → stock outperforms benchmark over the lookback
      < 0  → stock underperforms benchmark over the lookback
      = 0  → equal performance

    Parameters
    ----------
    stock_close : pd.Series
        Daily (or any timeframe) closing prices of the stock.
    benchmark_close : pd.Series
        Closing prices of the benchmark index (e.g., NIFTY spot).
        Must be aligned to the same index as stock_close.
    period : int
        Lookback window in bars. Default 55.

    Returns
    -------
    pd.Series
        RS values centred at 0, same index as stock_close.
        First `period` values are NaN (insufficient data).

    Raises
    ------
    ValueError
        If period < 1 or series lengths mismatch.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    # Align both series on the common index
    stock_close, benchmark_close = stock_close.align(benchmark_close, join="inner")

    if stock_close.empty:
        raise ValueError("stock_close and benchmark_close have no overlapping dates.")

    # Rolling ratio: current / lagged
    stock_return     = stock_close / stock_close.shift(period)
    benchmark_return = benchmark_close / benchmark_close.shift(period)

    # Avoid division by zero when benchmark return is exactly 0
    rs_raw = stock_return / benchmark_return.replace(0, np.nan)

    # Centre at 0: positive = outperform, negative = underperform
    rs = rs_raw - 1.0
    rs.name = f"RS_{period}"
    return rs


def relative_strength_rank(
    stocks_close: dict,
    benchmark_close: pd.Series,
    period: int = 55,
) -> pd.DataFrame:
    """
    Compute RS for multiple stocks and return a ranked DataFrame.

    Useful for universe-level screening — gives you a cross-sectional
    view of which stocks have the highest RS on each date.

    Parameters
    ----------
    stocks_close : dict
        {symbol: pd.Series} of closing prices.
    benchmark_close : pd.Series
        Benchmark closing prices (NIFTY).
    period : int
        RS lookback period. Default 55.

    Returns
    -------
    pd.DataFrame
        Columns = symbols, index = dates, values = RS scores.
    """
    rs_dict = {}
    for symbol, close in stocks_close.items():
        try:
            rs_dict[symbol] = relative_strength(close, benchmark_close, period)
        except Exception as e:
            print(f"[RS] Skipped {symbol}: {e}")
    return pd.DataFrame(rs_dict)
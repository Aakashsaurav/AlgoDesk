# schemas.py
from dataclasses import dataclass

TICK_COLUMNS = {
    "timestamp":      "datetime64[ns, Asia/Kolkata]",
    "instrument_key": "object",
    "symbol":         "object",
    "ltp":            "float32",
    "ltt":            "datetime64[ns, Asia/Kolkata]",
    "ltq":            "int32",
    "close_price":    "float32",
    "volume":         "int64",
    "oi":             "float32",
    "bid_price_1":    "float32",
    "ask_price_1":    "float32",
    "feed_mode":      "object",
    "feed_source":    "object",
}

CANDLE_COLUMNS = {
    "timestamp":      "datetime64[ns, Asia/Kolkata]",
    "symbol":         "object",
    "open":           "float32",
    "high":           "float32",
    "low":            "float32",
    "close":          "float32",
    "volume":         "int64",
}

GREEKS_COLUMNS = {
    "timestamp":          "datetime64[ns, Asia/Kolkata]",
    "symbol":             "object",
    "option_price":       "float32",
    "underlying_price":   "float32",
    "implied_volatility": "float32",
    "delta":              "float32",
    "theta":              "float32",
    "gamma":              "float32",
    "vega":               "float32",
    "rho":                "float32",
}

ORDER_COLUMNS = {
    "timestamp":      "datetime64[ns, Asia/Kolkata]",
    "order_id":       "object",
    "symbol":         "object",
    "action":         "object",
    "quantity":       "int32",
    "order_type":     "object",
    "limit_price":    "float32",
    "status":         "object",
}

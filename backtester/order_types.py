"""
backtester/order_types.py
--------------------------
Fill-check functions for pending entry orders and new types.

All functions are pure (no side-effects) and operate on scalar values —
making them trivially unit-testable and reusable by both the event loop
and a future tick-replay engine.
"""

def check_limit_fill(
    direction:   int,
    limit_price: float,
    open_p:      float,
    low:         float,
    high:        float,
) -> tuple[bool, float]:
    """
    Determine whether a pending LIMIT entry order fills on this bar.

    For a **buy limit** the order fills when ``low <= limit_price`` (price
    came down to the limit).  For a **sell limit** the order fills when
    ``high >= limit_price``.

    Gap handling: when the bar opens on the wrong side of the limit, we fill
    at open_p (better-than-limit fill), not at limit_price.

    Returns
    -------
    (filled, fill_price)
    """
    if direction == 1:   # BUY limit
        if open_p <= limit_price:              # gap down — fill at open
            return True, open_p
        if low <= limit_price:
            return True, limit_price
    else:                # SELL limit (short entry)
        if open_p >= limit_price:              # gap up — fill at open
            return True, open_p
        if high >= limit_price:
            return True, limit_price
    return False, 0.0


def check_stop_fill(
    direction:  int,
    stop_price: float,
    open_p:     float,
    low:        float,
    high:       float,
) -> tuple[bool, float]:
    """
    Determine whether a pending STOP entry order triggers on this bar.

    A buy stop triggers when ``high >= stop_price`` (breakout above stop).
    A sell stop triggers when ``low <= stop_price`` (breakdown below stop).

    Gap handling: when the bar opens through the stop, we fill at open_p.

    Returns
    -------
    (filled, fill_price)
    """
    if direction == 1:   # BUY stop (breakout)
        if open_p >= stop_price:
            return True, open_p
        if high >= stop_price:
            return True, stop_price
    else:                # SELL stop (breakdown)
        if open_p <= stop_price:
            return True, open_p
        if low <= stop_price:
            return True, stop_price
    return False, 0.0


def check_stop_limit_fill(
    direction:       int,
    stop_price:      float,
    limit_price:     float,
    open_p:          float,
    low:             float,
    high:            float,
    stop_triggered:  bool = False,
) -> tuple[bool, float, bool]:
    """
    Two-phase STOP-LIMIT fill check.

    Phase 1 — Stop trigger: is the stop level breached?
    Phase 2 — Limit check: if triggered, can we still fill at the limit?

    Returns
    -------
    (filled, fill_price, stop_hit)
        ``stop_hit`` remains True across bars once the stop is triggered,
        allowing the limit phase to try again on subsequent bars.
    """
    # ── Phase 1: stop trigger ──────────────────────────────────────────────
    if not stop_triggered:
        if direction == 1:
            stop_hit = open_p >= stop_price or high >= stop_price
        else:
            stop_hit = open_p <= stop_price or low <= stop_price
    else:
        stop_hit = True

    if not stop_hit:
        return False, 0.0, False

    # ── Phase 2: limit fill ────────────────────────────────────────────────
    if direction == 1:   # BUY stop-limit
        fill_price = max(open_p, stop_price)
        if fill_price <= limit_price:
            return True, fill_price, True
    else:                # SELL stop-limit
        fill_price = min(open_p, stop_price)
        if fill_price >= limit_price:
            return True, fill_price, True

    # Stop triggered but limit not reachable yet
    return False, 0.0, True

def check_bracket_fill(
    direction:   int,
    limit_price: float,
    open_p:      float,
    low:         float,
    high:        float,
) -> tuple[bool, float]:
    """Same as LIMIT fill logic — bracket fills at limit or better."""
    return check_limit_fill(direction, limit_price, open_p, low, high)

def check_cover_fill(
    direction:   int,
    limit_price: float,
    open_p:      float,
    low:         float,
    high:        float,
) -> tuple[bool, float]:
    """Same as LIMIT fill logic — cover fills at limit or better."""
    return check_limit_fill(direction, limit_price, open_p, low, high)

def check_amo_fill(
    bar_idx: int,
    signal_bar: int,
    open_p: float,
) -> tuple[bool, float]:
    """
    Fills at open_p of bar immediately after signal.
    """
    if bar_idx == signal_bar + 1:
        return True, open_p
    return False, 0.0

def check_gtt_fill(
    trigger_price: float,
    direction: int,
    open_p: float,
    high: float,
    low: float,
) -> tuple[bool, float]:
    """
    Like STOP fill but with indefinite expiry. Trigger check logic.
    Returns (triggered, fill_price).
    """
    return check_stop_fill(direction, trigger_price, open_p, low, high)
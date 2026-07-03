"""Position sizing and a pre-trade risk guard.

R-based sizing: risk a fixed amount ("1R") per trade. Quantity is chosen so that
being stopped out loses exactly 1R.

    risk_amount = fixed quote amount            (risk_mode="fixed")
                = equity * risk_per_trade       (risk_mode="percent")
    qty         = risk_amount / |entry - stop|
"""
from __future__ import annotations


def risk_amount(equity, risk_mode="fixed", risk_per_trade=10.0):
    if risk_mode == "fixed":
        return float(risk_per_trade)
    return float(equity) * float(risk_per_trade)


def size_position(equity, entry, stop, risk_mode="fixed", risk_per_trade=10.0,
                  min_stop_dist_pct=0.0):
    per_unit = abs(entry - stop)
    if per_unit <= 0:
        return 0.0
    # Reject stops that are too tight: a near-zero stop distance blows quantity
    # up toward full leverage, so the real risk far exceeds 1R.
    if min_stop_dist_pct > 0 and entry > 0 and (per_unit / abs(entry)) < min_stop_dist_pct:
        return 0.0
    return risk_amount(equity, risk_mode, risk_per_trade) / per_unit


def cap_qty_by_leverage(equity, price, qty, leverage=1.0):
    """Notional (qty*price) may not exceed equity*leverage."""
    if price <= 0 or qty <= 0:
        return qty
    max_notional = equity * leverage
    if qty * price > max_notional:
        return max_notional / price
    return qty


def order_risk_ok(entry, stop, qty, equity, risk_mode="fixed", risk_per_trade=10.0,
                  max_risk_mult=3.0, leverage=1.0):
    """Circuit breaker: reject a size whose true $ risk or notional is absurd.

    Catches sizing bugs (unit mix-ups, contract-size errors, abnormally tight
    stops) before they turn into oversized positions. Returns (ok, reason).
    """
    try:
        entry, stop, qty, equity = float(entry), float(stop), float(qty), float(equity)
    except (TypeError, ValueError):
        return False, "non-numeric input"
    if not (entry > 0 and stop > 0 and qty > 0):
        return False, f"non-positive entry={entry} stop={stop} qty={qty}"
    per_unit = abs(entry - stop)
    if per_unit <= 0:
        return False, "stop == entry (zero risk)"
    risk_usd = per_unit * qty
    target_r = risk_amount(equity, risk_mode, risk_per_trade)
    if target_r <= 0:
        target_r = max(1.0, equity * 0.01)
    if risk_usd > target_r * max_risk_mult:
        return False, f"real risk {risk_usd:.2f} > target {target_r:.2f} x{max_risk_mult:.0f}"
    notional = qty * entry
    if equity > 0 and notional > equity * leverage * 1.05:
        return False, f"notional {notional:.0f} > equity*leverage {equity*leverage:.0f}"
    return True, "ok"

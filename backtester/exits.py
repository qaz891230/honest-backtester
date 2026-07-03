"""Honest-fill, no-lookahead exit simulator.

This is the validated core of the framework. Given a filled entry, it scans
forward bar-by-bar and decides how the trade ends, applying realistic fill
assumptions:

  * Stops fill at the stop price and pay the taker fee + slippage (you cross the
    book when you're stopped out).
  * Targets fill at the target price and pay the maker fee by default (resting
    limit order). Set `tp_taker=True` for the pessimistic case where the resting
    take-profit is assumed to miss and you exit at market (taker + slippage).
  * Breakeven: after price reaches +`be_at_r`, the stop is moved to lock in
    `be_offset_r` (in R) or `be_offset_pct` (in price %). Crucially the moved
    stop is *capped at the trigger price* — you cannot lock in more than the
    move that actually happened on that bar. (Without this cap a fast simulator
    systematically over-counts breakeven winners; this cap is what makes the
    fast path agree with a bar-by-bar reference.)
  * Funding is charged per 8h funding window held (perp-style).

Within a single bar the order of touches is unknown from OHLC alone, so the
engine resolves ambiguity pessimistically (stop is assumed to fill before target
when both are inside the same bar's range).
"""
from __future__ import annotations
import math
import numpy as np


def _first_true(arr):
    if arr is None or arr.size == 0:
        return None
    k = int(np.argmax(arr))
    return k if arr[k] else None


def simulate_exit(high, low, close, epoch_s, entry_j, entry, stop, direction,
                  t1, t_final, qty, partial, costs, be_at_r=0.0,
                  be_offset_pct=0.0, be_offset_r=0.0, scan_cap=400, tp_taker=False):
    """Simulate a single trade from bar `entry_j` forward.

    Returns (net_pnl_quote, total_cost_quote, exit_index, reason) or None.

    costs = (taker_fee, maker_fee, slippage, funding_rate, apply_funding)
    All fees are fractions of notional (e.g. 0.0005 = 5 bps).
    """
    taker, maker, slip, funding, apply_funding = costs
    tp_fee = (taker + slip) if tp_taker else maker
    sign = 1 if direction == "long" else -1
    n = len(close)
    r_unit = abs(entry - stop)
    be_price = (entry + sign * r_unit * be_at_r) if (be_at_r and be_at_r > 0) else None
    end = min(n, entry_j + scan_cap)
    m = end - entry_j
    if m <= 0:
        return None
    H = high[entry_j:end]
    L = low[entry_j:end]
    if direction == "long":
        stop_hit = L <= stop
        t1_hit = H >= t1
        be_hit = (H >= be_price) if be_price is not None else None
        entry_hit_full = L <= entry
        tf_hit = (H >= t_final) if t_final is not None else None
    else:
        stop_hit = H >= stop
        t1_hit = L <= t1
        be_hit = (L <= be_price) if be_price is not None else None
        entry_hit_full = H >= entry
        tf_hit = (L <= t_final) if t_final is not None else None

    s0 = _first_true(stop_hit)
    a0 = _first_true(t1_hit)
    realized = 0.0
    cost = entry * qty * maker
    remaining = 1.0
    took_partial = False
    exit_k = None
    reason = "open_end"

    # Breakeven: if the BE trigger is reached before stop/target, move the stop.
    if be_price is not None:
        b0 = _first_true(be_hit)
        if b0 is not None and (s0 is None or b0 < s0) and (a0 is None or b0 < a0):
            if be_offset_r and be_offset_r > 0:
                stop = entry + sign * r_unit * be_offset_r
            else:
                stop = entry * (1 + sign * be_offset_pct)
            # Cap the moved stop at the trigger price (see module docstring).
            stop = min(stop, be_price) if direction == "long" else max(stop, be_price)
            _be_stop_hit = (L <= stop) if direction == "long" else (H >= stop)
            eh = _first_true(_be_stop_hit[b0 + 1:])
            s0 = (b0 + 1 + eh) if eh is not None else None

    if s0 is not None and (a0 is None or s0 <= a0):
        realized += (stop - entry) * sign * qty * remaining
        cost += stop * qty * remaining * (taker + slip)
        exit_k = s0
        remaining = 0.0
        reason = "stop"
    elif a0 is not None:
        realized += (t1 - entry) * sign * qty * partial
        cost += t1 * qty * partial * tp_fee
        remaining -= partial
        took_partial = True
        exit_k = a0
        if remaining <= 1e-9:
            reason = "target_first_full"
        else:
            s2 = _first_true(entry_hit_full[a0:])
            f2 = _first_true(tf_hit[a0:]) if tf_hit is not None else None
            if s2 is not None and (f2 is None or s2 <= f2):
                exit_k = a0 + s2
                remaining = 0.0
                reason = "partial_then_stop"
            elif f2 is not None:
                realized += (t_final - entry) * sign * qty * remaining
                cost += t_final * qty * remaining * tp_fee
                exit_k = a0 + f2
                remaining = 0.0
                reason = "target_final"

    # Anything still open at the scan horizon is marked-to-market at the last close.
    if remaining > 1e-9:
        last_px = float(close[end - 1])
        realized += (last_px - entry) * sign * qty * remaining
        cost += last_px * qty * remaining * maker
        exit_k = m - 1
        remaining = 0.0
        reason = "open_end_partial" if took_partial else "open_end"
    if exit_k is None:
        return None
    exit_idx = entry_j + exit_k
    if apply_funding:
        ka = math.ceil(epoch_s[entry_j] / 28800.0)
        kb = math.floor(epoch_s[exit_idx] / 28800.0)
        cost += funding * (entry * qty) * max(0, kb - ka + 1)
    return (realized - cost, cost, exit_idx, reason)

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
    move that actually happened on that bar.
  * Funding is charged per 8h funding window held (perp-style).

Within a single bar the order of touches is unknown from OHLC alone, so the
engine resolves ambiguity pessimistically (stop is assumed to fill before target
when both are inside the same bar's range).

The result also carries an `events` list — every discrete action the engine took
on the trade (entry, breakeven move, partial take-profit, final exit) with the
bar index and price — so a run can be drawn on a chart and verified visually.
"""
from __future__ import annotations
from collections import namedtuple
import math
import numpy as np

# Rich result so callers get the real fill price and the action timeline.
ExitResult = namedtuple("ExitResult", "net cost exit_index reason exit_price events")


def _first_true(arr):
    if arr is None or arr.size == 0:
        return None
    k = int(np.argmax(arr))
    return k if arr[k] else None


def simulate_exit(high, low, close, epoch_s, entry_j, entry, stop, direction,
                  t1, t_final, qty, partial, costs, be_at_r=0.0,
                  be_offset_pct=0.0, be_offset_r=0.0, scan_cap=400, tp_taker=False,
                  be_intrabar="honest"):
    """Simulate a single trade from bar `entry_j` forward.

    Returns an ExitResult(net, cost, exit_index, reason, exit_price, events) or None.

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
    exit_price = None
    events = [{"type": "entry", "index": entry_j, "price": float(entry),
               "direction": direction}]

    # Breakeven: if the BE trigger is reached before stop/target, move the stop.
    if be_price is not None:
        b0 = _first_true(be_hit)
        _honest = (be_intrabar != "optimistic")
        if b0 is not None and (s0 is None or b0 < s0) and (a0 is None or (b0 <= a0 if _honest else b0 < a0)):
            if be_offset_r and be_offset_r > 0:
                stop = entry + sign * r_unit * be_offset_r
            else:
                stop = entry * (1 + sign * be_offset_pct)
            # Cap the moved stop at the trigger price (see module docstring).
            stop = min(stop, be_price) if direction == "long" else max(stop, be_price)
            events.append({"type": "breakeven", "index": entry_j + b0,
                           "price": float(stop)})
            # Intrabar honesty (default): OHLC bars cannot tell us the tick path inside
            # the trigger bar. The optimistic legacy treated the trigger bar as "held"
            # (lock-out only checked from the NEXT bar) and booked a target hit in the
            # SAME bar as a clean TP. Both flatter tight locks: live trading showed a
            # 69% vs 32% breakeven-exit-rate divergence (4.7 sigma). Honest rule: if the
            # trigger bar CLOSES beyond the moved stop, the trade is stopped on that bar;
            # a same-bar target only counts if the close held above the moved stop.
            _c0 = close[entry_j + b0]
            _lock_b0 = _honest and ((_c0 < stop) if direction == "long" else (_c0 > stop))
            if _lock_b0:
                s0 = b0
                if a0 is not None and a0 >= b0:
                    a0 = None
            elif _honest and a0 is not None and a0 == b0:
                s0 = None   # same-bar target with close holding the lock -> TP branch
            else:
                _be_stop_hit = (L <= stop) if direction == "long" else (H >= stop)
                eh = _first_true(_be_stop_hit[b0 + 1:])
                s0 = (b0 + 1 + eh) if eh is not None else None

    if s0 is not None and (a0 is None or s0 <= a0):
        realized += (stop - entry) * sign * qty * remaining
        cost += stop * qty * remaining * (taker + slip)
        exit_k = s0
        remaining = 0.0
        reason = "stop"
        exit_price = float(stop)
    elif a0 is not None:
        realized += (t1 - entry) * sign * qty * partial
        cost += t1 * qty * partial * tp_fee
        remaining -= partial
        took_partial = True
        exit_k = a0
        if partial < 1.0 - 1e-9:
            events.append({"type": "partial", "index": entry_j + a0, "price": float(t1)})
        if remaining <= 1e-9:
            reason = "target_first_full"
            exit_price = float(t1)
        else:
            s2 = _first_true(entry_hit_full[a0:])
            f2 = _first_true(tf_hit[a0:]) if tf_hit is not None else None
            if s2 is not None and (f2 is None or s2 <= f2):
                exit_k = a0 + s2
                remaining = 0.0
                reason = "partial_then_stop"
                exit_price = float(entry)  # remainder closed at breakeven (entry)
            elif f2 is not None:
                realized += (t_final - entry) * sign * qty * remaining
                cost += t_final * qty * remaining * tp_fee
                exit_k = a0 + f2
                remaining = 0.0
                reason = "target_final"
                exit_price = float(t_final)

    # Anything still open at the scan horizon is marked-to-market at the last close.
    if remaining > 1e-9:
        last_px = float(close[end - 1])
        realized += (last_px - entry) * sign * qty * remaining
        cost += last_px * qty * remaining * maker
        exit_k = m - 1
        remaining = 0.0
        reason = "open_end_partial" if took_partial else "open_end"
        exit_price = last_px
    if exit_k is None:
        return None
    exit_idx = entry_j + exit_k
    if exit_price is None:
        exit_price = float(close[exit_idx])
    if apply_funding:
        ka = math.ceil(epoch_s[entry_j] / 28800.0)
        kb = math.floor(epoch_s[exit_idx] / 28800.0)
        cost += funding * (entry * qty) * max(0, kb - ka + 1)

    events.append({"type": "exit", "index": exit_idx, "price": float(exit_price),
                   "reason": reason})
    return ExitResult(realized - cost, cost, exit_idx, reason, float(exit_price), events)

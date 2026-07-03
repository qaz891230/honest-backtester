"""Performance metrics for a list of Trade objects."""
from __future__ import annotations


def summary(trades, equity, start_equity, total_cost, curve=None, span_days=None):
    wins = [t for t in trades if t.pnl_quote > 0]
    losses = [t for t in trades if t.pnl_quote <= 0]
    gw = sum(t.pnl_quote for t in wins)
    gl = -sum(t.pnl_quote for t in losses)
    rs = [t.pnl_r for t in trades]

    mdd = 0.0
    if curve:
        peak = curve[0][1]
        for _, e in curve:
            peak = max(peak, e)
            if peak > 0:
                mdd = max(mdd, (peak - e) / peak)

    streak = mx = 0
    for t in trades:
        if t.pnl_quote <= 0:
            streak += 1
            mx = max(mx, streak)
        else:
            streak = 0

    win_rs = [t.pnl_r for t in wins]
    loss_rs = [t.pnl_r for t in losses]

    # Distribution of outcomes by exit reason and by R bucket.
    reasons = {}
    for t in trades:
        d = reasons.setdefault(t.reason or "?", {"n": 0, "win": 0, "sum_r": 0.0})
        d["n"] += 1
        d["sum_r"] += t.pnl_r
        if t.pnl_quote > 0:
            d["win"] += 1
    for d in reasons.values():
        d["sum_r"] = round(float(d["sum_r"]), 2)

    buckets = {"<=-1R": 0, "-1..0R": 0, "0..1R": 0, "1..2R": 0, ">2R": 0}
    for t in trades:
        r = t.pnl_r
        if r <= -1:
            buckets["<=-1R"] += 1
        elif r < 0:
            buckets["-1..0R"] += 1
        elif r < 1:
            buckets["0..1R"] += 1
        elif r < 2:
            buckets["1..2R"] += 1
        else:
            buckets[">2R"] += 1

    longs = [t for t in trades if t.direction == "long"]
    shorts = [t for t in trades if t.direction == "short"]

    def _wr(ts):
        return round(sum(1 for t in ts if t.pnl_quote > 0) / len(ts), 3) if ts else None

    total_r = sum(rs)
    out = {
        "n_trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3) if trades else 0.0,
        "profit_factor": round(gw / gl, 2) if gl else None,
        "expectancy_r": round(total_r / len(rs), 3) if rs else 0.0,
        "total_r": round(total_r, 2),
        "avg_win_r": round(sum(win_rs) / len(win_rs), 2) if win_rs else 0.0,
        "avg_loss_r": round(sum(loss_rs) / len(loss_rs), 2) if loss_rs else 0.0,
        "total_pnl": round(equity - start_equity, 2),
        "return_pct": round((equity / start_equity - 1) * 100, 2),
        "final_equity": round(equity, 2),
        "total_cost": round(total_cost, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "max_loss_streak": mx,
        "long_n": len(longs), "long_wr": _wr(longs),
        "short_n": len(shorts), "short_wr": _wr(shorts),
        "reasons": reasons,
        "r_dist": buckets,
    }
    if span_days and span_days > 0:
        out["span_days"] = span_days
        out["per_year_r"] = round(total_r / (span_days / 365.0), 1)
        out["trades_per_week"] = round(len(trades) / (span_days / 7.0), 2)
    return out

"""Candlestick visualization of a backtest — every engine action on the chart.

Draws OHLC candles and overlays, for each trade, every discrete action the engine
took: entry, the stop and target levels, any breakeven move, partial take-profit,
and the final exit (coloured by reason). This is a *verification* tool: if the
engine is doing something wrong, you will usually see it here.

Headless by default (saves PNG via the Agg backend) so it works over SSH / CI.

    from backtester.plot import plot_trade, plot_run
    plot_trade(df, res["_trades"][0], path="trade.png")     # zoom one trade
    plot_run(df, res, start=0, end=300, path="overview.png") # a window overview

Requires matplotlib (pip install matplotlib).
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # headless; safe to import without a display
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# Exit-reason -> (marker, colour, label)
_EXIT_STYLE = {
    "stop":              ("X", "#e74c3c", "stop"),
    "target_first_full": ("*", "#2ecc71", "target"),
    "target_final":      ("*", "#2ecc71", "final target"),
    "partial_then_stop": ("s", "#e67e22", "breakeven exit"),
    "open_end":          ("o", "#7f8c8d", "time exit"),
    "open_end_partial":  ("o", "#7f8c8d", "time exit"),
}
_UP = "#26a69a"
_DOWN = "#ef5350"


def _draw_candles(ax, df, i0, i1):
    i0 = max(0, i0)
    i1 = min(len(df), i1)
    o = df["open"].values; h = df["high"].values
    l = df["low"].values; c = df["close"].values
    for k in range(i0, i1):
        up = c[k] >= o[k]
        col = _UP if up else _DOWN
        ax.plot([k, k], [l[k], h[k]], color=col, linewidth=0.7, zorder=1)
        lo = min(o[k], c[k]); hgt = abs(c[k] - o[k]) or (h[k] - l[k]) * 1e-3 or 1e-9
        ax.add_patch(Rectangle((k - 0.3, lo), 0.6, hgt, color=col, zorder=2))
    return i0, i1


def _date_ticks(ax, df, i0, i1, n=6):
    import numpy as np
    xs = np.linspace(i0, max(i0, i1 - 1), n).astype(int)
    ax.set_xticks(xs)
    ax.set_xticklabels([str(df.index[x])[:16] for x in xs], rotation=20,
                       ha="right", fontsize=8)


def plot_trade(df, trade, pad=30, path=None, title=None):
    """Zoom into a single trade and annotate every action.

    Shows: entry (triangle), initial stop (red dashed), final target (green
    dashed), any breakeven move (grey diamond + line), partial TP (orange dot),
    and the final exit (marker coloured by reason).
    """
    ev = trade.meta.get("events", []) if getattr(trade, "meta", None) else []
    i0 = trade.entry_index - pad
    i1 = trade.exit_index + pad + 1
    fig, ax = plt.subplots(figsize=(12, 6))
    i0, i1 = _draw_candles(ax, df, i0, i1)

    long = trade.direction == "long"
    # Level lines spanning the life of the trade.
    ax.hlines(trade.stop, trade.entry_index, trade.exit_index, colors="#e74c3c",
              linestyles="--", linewidth=1.1, label="initial stop", zorder=3)
    ax.hlines(trade.final_target, trade.entry_index, trade.exit_index,
              colors="#2ecc71", linestyles="--", linewidth=1.1, label="final target",
              zorder=3)

    # Per-action markers from the event timeline.
    seen = set()
    for e in ev:
        typ = e["type"]; x = e["index"]; y = e["price"]
        if typ == "entry":
            m = "^" if long else "v"
            ax.scatter([x], [y], marker=m, s=140, color="#2980b9",
                       edgecolor="white", linewidth=0.6, zorder=6,
                       label=None if "entry" in seen else f"entry ({trade.direction})")
            seen.add("entry")
        elif typ == "breakeven":
            ax.scatter([x], [y], marker="D", s=70, color="#95a5a6",
                       edgecolor="black", linewidth=0.5, zorder=6,
                       label=None if "be" in seen else "breakeven move")
            ax.hlines(y, x, trade.exit_index, colors="#95a5a6", linestyles=":",
                      linewidth=1.0, zorder=3)
            seen.add("be")
        elif typ == "partial":
            ax.scatter([x], [y], marker="o", s=70, color="#e67e22",
                       edgecolor="white", linewidth=0.5, zorder=6,
                       label=None if "partial" in seen else "partial take-profit")
            seen.add("partial")
        elif typ == "exit":
            mk, col, lab = _EXIT_STYLE.get(e.get("reason", ""), ("o", "#7f8c8d", "exit"))
            ax.scatter([x], [y], marker=mk, s=170, color=col, edgecolor="white",
                       linewidth=0.6, zorder=7, label=f"exit: {lab}")

    # Entry -> exit connector, coloured by P&L.
    conn = "#2ecc71" if trade.pnl_r >= 0 else "#e74c3c"
    ax.plot([trade.entry_index, trade.exit_index], [trade.entry, trade.exit_price],
            color=conn, linewidth=1.0, alpha=0.6, zorder=4)

    _date_ticks(ax, df, i0, i1)
    ax.set_ylabel("price")
    if title is None:
        title = (f"{trade.direction.upper()} @ bar {trade.entry_index} -> {trade.exit_index}"
                 f"   reason={trade.reason}   R={trade.pnl_r:+.2f}")
    ax.set_title(title, fontsize=11)
    ax.legend(loc="best", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.15)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
        plt.close(fig)
        return path
    return fig


def plot_run(df, result, start=None, end=None, path=None, title=None,
             show_levels=False):
    """Overview of a window: candles with every trade's entry/exit overlaid.

    Entries are blue triangles, exits are coloured by reason, and each trade has a
    faint entry->exit connector (green win / red loss). Set show_levels=True to
    also draw each trade's stop/target lines (readable only for few trades).
    """
    trades = result["_trades"] if isinstance(result, dict) else result
    i0 = 0 if start is None else start
    i1 = len(df) if end is None else end
    fig, ax = plt.subplots(figsize=(14, 7))
    i0, i1 = _draw_candles(ax, df, i0, i1)

    in_win = [t for t in trades if i0 <= t.entry_index < i1]
    lab_done = set()
    for t in in_win:
        long = t.direction == "long"
        ax.scatter([t.entry_index], [t.entry], marker="^" if long else "v", s=70,
                   color="#2980b9", edgecolor="white", linewidth=0.4, zorder=6,
                   label=None if "entry" in lab_done else "entry")
        lab_done.add("entry")
        mk, col, lab = _EXIT_STYLE.get(t.reason, ("o", "#7f8c8d", "exit"))
        ex = min(t.exit_index, i1 - 1)
        ax.scatter([ex], [t.exit_price], marker=mk, s=80, color=col,
                   edgecolor="white", linewidth=0.4, zorder=7,
                   label=None if lab in lab_done else lab)
        lab_done.add(lab)
        conn = "#2ecc71" if t.pnl_r >= 0 else "#e74c3c"
        ax.plot([t.entry_index, ex], [t.entry, t.exit_price], color=conn,
                linewidth=0.8, alpha=0.4, zorder=4)
        if show_levels:
            ax.hlines(t.stop, t.entry_index, ex, colors="#e74c3c",
                      linestyles="--", linewidth=0.6, alpha=0.5, zorder=3)
            ax.hlines(t.final_target, t.entry_index, ex, colors="#2ecc71",
                      linestyles="--", linewidth=0.6, alpha=0.5, zorder=3)

    _date_ticks(ax, df, i0, i1)
    ax.set_ylabel("price")
    n_win = len(in_win)
    ax.set_title(title or f"backtest overview — bars {i0}..{i1}  ({n_win} trades)",
                 fontsize=11)
    ax.legend(loc="best", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.15)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
        plt.close(fig)
        return path
    return fig

"""
stats.py — summary metrics for a backtest run (raw points, no brokerage).
"""
from collections import defaultdict


def summarize(trades: list) -> dict:
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "total_points": 0.0, "avg_points": 0.0,
            "max_drawdown": 0.0, "best": None, "worst": None,
            "longest_win_streak": 0, "longest_loss_streak": 0,
            "per_strike": {},
        }

    closed = [t for t in trades if t.points is not None]
    wins = [t for t in closed if t.points > 0]
    losses = [t for t in closed if t.points <= 0]
    total = round(sum(t.points for t in closed), 2)

    equity, peak, dd = 0.0, 0.0, 0.0
    for t in closed:
        equity += t.points
        peak = max(peak, equity)
        dd = max(dd, peak - equity)

    lw = ll = cur_w = cur_l = 0
    for t in closed:
        if t.points > 0:
            cur_w += 1; cur_l = 0
            lw = max(lw, cur_w)
        else:
            cur_l += 1; cur_w = 0
            ll = max(ll, cur_l)

    per_strike = defaultdict(lambda: {"trades": 0, "points": 0.0, "wins": 0})
    for t in closed:
        b = per_strike[t.strike]
        b["trades"] += 1
        b["points"] = round(b["points"] + t.points, 2)
        if t.points > 0:
            b["wins"] += 1

    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(100.0 * len(wins) / len(closed), 1) if closed else 0.0,
        "total_points": total,
        "avg_points": round(total / len(closed), 2) if closed else 0.0,
        "max_drawdown": round(dd, 2),
        "best": max(closed, key=lambda t: t.points).points if closed else None,
        "worst": min(closed, key=lambda t: t.points).points if closed else None,
        "longest_win_streak": lw,
        "longest_loss_streak": ll,
        "per_strike": dict(per_strike),
    }
"""
bep_logic.py — pure, side-effect-free decision functions for the BEP backtest.

No API calls, no UI, no state. Candle shape (from upstox_client):
[ts, open, high, low, close, ...] where ts looks like "2026-10-20T09:15:00+05:30".
"""
import config


def qualify(first_candle, bep: float) -> bool:
    """The 09:15-09:20 qualification: candle TOUCHED BEP, CLOSED above it, AND is green."""
    if first_candle is None or bep is None:
        return False
    o, h, l, c = float(first_candle[1]), float(first_candle[2]), float(first_candle[3]), float(first_candle[4])
    return l <= bep <= h and c > bep and c > o


def branch(close: float, bep: float) -> str:
    """Which entry path applies at a qualifying (or re-entry flip) candle."""
    gap = float(close) - float(bep)
    return "enter_next_open" if gap <= config.GAP_THRESHOLD else "park"


def flip_close_above(candle, bep: float) -> bool:
    """A fresh touch + close-above flip AND is green (used for parked legs and re-entries)."""
    if candle is None or bep is None:
        return False
    o, h, l, c = float(candle[1]), float(candle[2]), float(candle[3]), float(candle[4])
    return l <= bep <= h and c > bep and c > o


def limit_touched(candle, bep: float) -> bool:
    """Has the candle traded up to the parked limit at BEP + 1?"""
    if candle is None or bep is None:
        return False
    return float(candle[2]) >= float(bep) + 1.0


def closed_below(candle, bep: float) -> bool:
    """Did the candle CLOSE below BEP (wick below does not count)?"""
    if candle is None or bep is None:
        return False
    return float(candle[4]) < float(bep)


def target_hit(candle, entry: float) -> bool:
    """Has the candle reached entry + TARGET_POINTS intrabar?"""
    if candle is None or entry is None:
        return False
    return float(candle[2]) >= float(entry) + config.TARGET_POINTS
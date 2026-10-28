"""
trade_sim.py — converts engine signals into concrete fills and points PnL.
"""
from dataclasses import dataclass, field
from typing import Optional

import config


@dataclass
class Fill:
    time: str            # "HH:MM" of the candle that produced the fill
    price: float         # fill price in option points
    reason: str          # "open" | "limit" | "target" | "sl"


@dataclass
class Trade:
    strike: int
    leg: str                       # "CE" | "PE"
    branch: str                    # "<=10" | ">10"
    signal_time: str
    bep: Optional[float] = None    # BEP for this strike on this date
    entry: Optional[Fill] = None
    exit: Optional[Fill] = None
    points: Optional[float] = None
    trade_no: int = 1
    extra: dict = field(default_factory=dict)

    def close(self, exit_fill: Fill):
        self.exit = exit_fill
        if self.entry is not None:
            self.points = round(exit_fill.price - self.entry.price, 2)


def open_fill(candle) -> Fill:
    return Fill(time=_hhmm(candle[0]), price=float(candle[1]), reason="open")


def limit_fill(bep: float, candle) -> Fill:
    return Fill(time=_hhmm(candle[0]), price=float(bep) + 1.0, reason="limit")


def target_fill(candle, entry_price: float) -> Fill:
    return Fill(time=_hhmm(candle[0]),
                price=float(entry_price) + config.TARGET_POINTS, reason="target")


def sl_fill(candle) -> Fill:
    return Fill(time=_hhmm(candle[0]), price=float(candle[4]), reason="sl")


def _hhmm(ts: str) -> str:
    return ts[11:16] if len(ts) >= 16 else ts
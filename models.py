"""
models.py — small shared data shapes for the BEP backtest.

Trade and Fill live in trade_sim.py. What remains here is the display-facing
BoardCell and a BacktestRun container.
"""
from dataclasses import dataclass, field


@dataclass
class BoardCell:
    """One coloured cell in the replay grid: state of a leg at one candle."""
    state: str          # IDLE | ARM_NEXT_OPEN | PARKED | IN_TRADE | DEAD | DONE
    label: str
    bep: float
    close: float
    entry_price: float | None = None


@dataclass
class BacktestRun:
    date: str
    expiry: str
    strikes: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    board: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
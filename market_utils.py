"""
market_utils.py — Nifty strike helpers, expiry cycle, and option contract lookup.
"""
from datetime import datetime, timedelta
import pytz

import config

IST = pytz.timezone("Asia/Kolkata")


def nearest_strike(ltp: float, interval: int = config.STRIKE_INTERVAL) -> int:
    """Rounds Nifty LTP to the nearest tradable strike."""
    return int(round(ltp / interval) * interval)


def current_weekly_expiry(client):
    """
    Nearest weekly expiry date for Nifty options, e.g. '2026-10-27', or None.
    """
    expiries, err = client.fetch_option_expiries(config.NIFTY_OPTION_UNDERLYING_KEY)
    if err or not expiries:
        return None
    return expiries[0]


def current_weekly_expiry_dates(client):
    """
    Returns (expiry_date_str, [valid_backtest_dates]) for the current weekly
    expiry cycle. Nifty weekly options expire on Tuesdays, so the cycle runs
    from the Wednesday before expiry through expiry Tuesday. The date list
    excludes weekends, future dates, and MARKET_HOLIDAYS.
    """
    expiry_str = current_weekly_expiry(client)
    if not expiry_str:
        return None, []

    expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
    cycle_start = expiry_date - timedelta(days=6)   # previous Wednesday
    today = datetime.now(IST).date()

    dates = []
    d = cycle_start
    while d <= expiry_date:
        if d.weekday() < 5 and d <= today \
                and d.strftime("%Y-%m-%d") not in config.MARKET_HOLIDAYS:
            dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return expiry_str, dates


# expiry -> {strike: {"CE": instrument_key, "PE": instrument_key}}
_option_key_cache: dict = {}


def option_instrument_keys(client, expiry: str):
    """
    CE/PE instrument keys for every strike of the given expiry, fetched once
    and cached. Returns ({strike: {"CE": key, "PE": key}}, None) or (None, err).
    """
    if expiry in _option_key_cache:
        return _option_key_cache[expiry], None
    contracts, err = client.fetch_option_contracts(config.NIFTY_OPTION_UNDERLYING_KEY, expiry)
    if contracts is None:
        return None, err
    mapping: dict = {}
    for c in contracts:
        strike = c.get("strike_price")
        opt = c.get("instrument_type")
        ik = c.get("instrument_key")
        if strike is None or opt not in ("CE", "PE") or not ik:
            continue
        mapping.setdefault(int(strike), {})[opt] = ik
    _option_key_cache[expiry] = mapping
    return mapping, None
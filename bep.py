"""
bep.py — Break-Even Point per strike, calculated in-app.

    BEP = (CE previous-day close + PE previous-day close) / 2

"Previous-day" means the most recent daily close dated STRICTLY BEFORE the
date being backtested. No CSV upload; every strike is calculated.
Results are cached per (backtest_date, expiry, strike).
"""
import time
from concurrent.futures import ThreadPoolExecutor

import market_utils

FETCH_WORKERS = 8
FAIL_RETRY_SECONDS = 300

_cache: dict = {}             # (date_str, expiry, strike) -> BEP
_fail:  dict = {}             # (date_str, expiry, strike) -> monotonic time of last failure


def clear_cache():
    _cache.clear()
    _fail.clear()


def get_bep_for_date(client, expiry: str, strike: int, date_str: str):
    """Returns (bep, "calc") on success, (None, None) on failure."""
    strike = int(strike)
    key = (date_str, expiry, strike)
    if key in _cache:
        return _cache[key], "calc"
    if time.monotonic() - _fail.get(key, -1e9) < FAIL_RETRY_SECONDS:
        return None, None

    mapping, _err = market_utils.option_instrument_keys(client, expiry)
    legs = (mapping or {}).get(strike, {})
    ce_ik, pe_ik = legs.get("CE"), legs.get("PE")
    if not ce_ik or not pe_ik:
        _fail[key] = time.monotonic()
        return None, None

    ce_pdc, _ = client.fetch_close_before(ce_ik, date_str)
    pe_pdc, _ = client.fetch_close_before(pe_ik, date_str)
    if ce_pdc is None or pe_pdc is None:
        _fail[key] = time.monotonic()
        return None, None

    level = round((ce_pdc + pe_pdc) / 2, 2)
    _cache[key] = level
    return level, "calc"


def prefetch_for_date(client, expiry: str, strikes: list, date_str: str) -> int:
    """Warm the cache for a whole strike list in parallel. Returns the number
    of strikes whose BEP is now known."""
    def one(s):
        level, _ = get_bep_for_date(client, expiry, int(s), date_str)
        return level is not None

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        return sum(1 for ok in ex.map(one, strikes) if ok)
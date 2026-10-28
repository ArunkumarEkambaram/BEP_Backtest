"""
backtest_engine.py — replays a single date's 5-minute candles through the BEP
strategy, leg by leg, and emits trade records plus per-candle board states.

Per leg (strike x {"CE","PE"}):
  IDLE
    first candle (09:15-09:20):
      not qualified                        -> DEAD
      qualified, close-bep <= 10           -> ARM_NEXT_OPEN
      qualified, close-bep >  10           -> PARKED (limit BEP+1, 3 candles)
  ARM_NEXT_OPEN
    next candle open -> entry at open       -> IN_TRADE
  PARKED
    limit touched in next 3 candles         -> entry at BEP+1 -> IN_TRADE
    closed below BEP before the fill        -> DEAD
    3 candles elapse without a fill         -> stay PARKED, wait for a flip
    later candle: fresh touch + close above -> re-branch
  IN_TRADE (checks start AFTER entry; target beats SL in a candle)
    high >= entry+30 -> exit target (entry+30)
    close < BEP      -> exit SL (close)
    After exit: trades_taken < 2 -> IDLE (one re-entry allowed)
                trades_taken >= 2 -> DONE
"""
from concurrent.futures import ThreadPoolExecutor

import config
import market_utils
import bep
import bep_logic
import trade_sim


FETCH_WORKERS = 8


def run_backtest(client, date_str: str, expiry: str, log_fn=print) -> dict:
    summary = {"date": date_str, "expiry": expiry, "trades": [],
               "board": {}, "errors": [], "strikes": []}

    # 1. Nifty 5-min candles for the day (validates the session)
    nifty_candles, err = client.fetch_intraday_candles_for_day(
        config.NIFTY_INDEX_KEY, date_str, config.CANDLE_MINUTES)
    if nifty_candles is None:
        summary["errors"].append(f"Nifty candles failed: {err}")
        return summary
    if not nifty_candles:
        summary["errors"].append(f"No Nifty candles for {date_str} (holiday?).")
        return summary

    # 2. Resolve every strike of this expiry -> {strike: {"CE": ik, "PE": ik}}
    mapping, err = market_utils.option_instrument_keys(client, expiry)
    if mapping is None:
        summary["errors"].append(f"Option contract lookup failed: {err}")
        return summary

    # 3. Strike universe = ATM +/- BEP_BAND_STRIKES, where ATM = nearest strike
    #    to the 09:15 candle's OPEN on the backtest date. The 09:15 open is the
    #    first print of the day (no need to wait for the candle to close).
    #    Guard: fail cleanly if the first candle isn't the 09:15 one.
    first_ts = nifty_candles[0][0][11:16]   # "HH:MM"
    if first_ts != "09:15":
        summary["errors"].append(
            f"First Nifty candle is at {first_ts}, expected 09:15. "
            f"Check the day is a normal session and data is complete.")
        return summary

    all_strikes = sorted(mapping.keys())
    day_open = float(nifty_candles[0][1])   # 09:15:00 open
    atm = market_utils.nearest_strike(day_open)
    k = config.BEP_BAND_STRIKES
    if k is None:
        strikes = all_strikes
        log_fn(f"Backtest {date_str}: full universe ({len(strikes)} strikes) "
               f"around day-open ATM {atm}.")
    else:
        strikes = [s for s in all_strikes
                   if abs(s - atm) <= k * config.STRIKE_INTERVAL]
        if not strikes:
            summary["errors"].append(
                f"No strikes within ±{k} ({k * config.STRIKE_INTERVAL} pts) "
                f"of ATM {atm} for expiry {expiry}.")
            return summary
        log_fn(f"Backtest {date_str}: day-open {day_open:.2f} -> ATM {atm}, "
               f"strikes {strikes[0]}..{strikes[-1]} ({len(strikes)} strikes).")
    summary["strikes"] = strikes

    # 4. Compute BEP per strike
    beps = _resolve_beps(client, strikes, expiry, date_str, log_fn)
    if not beps:
        summary["errors"].append("No usable BEPs for any strike.")
        return summary

    # 5. Fetch 5-min candles for every leg in parallel
    leg_candles = _fetch_leg_candles(client, strikes, mapping, date_str, log_fn)

    # 6. Run the state machine per leg
    all_trades = []
    board = {}
    for strike in strikes:
        bep_level = beps.get(strike)
        if bep_level is None:
            continue
        for opt in ("CE", "PE"):
            ik = (mapping.get(strike) or {}).get(opt)
            candles = leg_candles.get((strike, opt)) or []
            if not ik or not candles:
                continue
            trades, cells = _run_leg(
                strike=strike, leg=opt, bep_level=bep_level, candles=candles,
            )
            all_trades.extend(trades)
            for key, cell in cells.items():
                board.setdefault(key, []).append(cell)

    all_trades.sort(key=lambda t: (t.entry.time if t.entry else "", t.strike, t.leg))
    summary["trades"] = all_trades
    summary["board"] = board
    log_fn(f"Backtest {date_str}: {len(all_trades)} trade(s) taken.")
    return summary


def _run_leg(strike: int, leg: str, bep_level: float, candles: list):
    trades, cells = [], {}
    if len(candles) < 2:
        return trades, cells

    state = "IDLE"
    trades_taken = 0
    entry_fill = None
    current_trade = None
    park_start_idx = None
    branch_label = None

    first = candles[0]
    first_close = float(first[4])

    for idx, candle in enumerate(candles):
        key = _candle_key(candle)
        prev_state = state

        if state == "IDLE":
            if idx == 0:
                if not bep_logic.qualify(candle, bep_level):
                    state = "DEAD"
                else:
                    action = bep_logic.branch(first_close, bep_level)
                    branch_label = "<=10" if action == "enter_next_open" else ">10"
                    if action == "enter_next_open":
                        state = "ARM_NEXT_OPEN"
                    else:
                        state = "PARKED"
                        park_start_idx = idx
            
            # Kill switch for re-entry: if idle and candle closes below BEP, die.
            elif bep_logic.closed_below(candle, bep_level):
                state = "DEAD"
                
            elif trades_taken < config.MAX_TRADES_PER_LEG and \
                    bep_logic.flip_close_above(candle, bep_level):
                
                action = bep_logic.branch(float(candle[4]), bep_level)
                branch_label = "<=10" if action == "enter_next_open" else ">10"
                if action == "enter_next_open":
                    state = "ARM_NEXT_OPEN"
                else:
                    state = "PARKED"
                    park_start_idx = idx

        elif state == "ARM_NEXT_OPEN" and idx > 0:
            entry_fill = trade_sim.open_fill(candle)
            current_trade = _new_trade(strike, leg, branch_label, first, entry_fill, trades_taken + 1, bep_level)
            state = "IN_TRADE"

        elif state == "PARKED":
            if bep_logic.closed_below(candle, bep_level):
                state = "DEAD"
            elif (park_start_idx is not None) and \
                    (idx - park_start_idx) <= config.PARK_CANDLES and \
                    bep_logic.limit_touched(candle, bep_level):
                entry_fill = trade_sim.limit_fill(bep_level, candle)
                current_trade = _new_trade(strike, leg, branch_label, first, entry_fill, trades_taken + 1, bep_level)
                state = "IN_TRADE"
            elif (park_start_idx is not None) and (idx - park_start_idx) > config.PARK_CANDLES:
                if bep_logic.flip_close_above(candle, bep_level) and \
                        trades_taken < config.MAX_TRADES_PER_LEG:
                    action = bep_logic.branch(float(candle[4]), bep_level)
                    branch_label = "<=10" if action == "enter_next_open" else ">10"
                    if action == "enter_next_open":
                        state = "ARM_NEXT_OPEN"
                    else:
                        state = "PARKED"
                        park_start_idx = idx

        elif state == "IN_TRADE" and entry_fill is not None:
            if _candle_key(candle) == entry_fill.time:
                pass  # entry candle: no exit check
            elif bep_logic.target_hit(candle, entry_fill.price):
                exit_fill = trade_sim.target_fill(candle, entry_fill.price)
                current_trade.close(exit_fill)
                trades.append(current_trade)
                trades_taken += 1
                entry_fill = current_trade = None
                state = "IDLE" if trades_taken < config.MAX_TRADES_PER_LEG else "DONE"
            elif bep_logic.closed_below(candle, bep_level):
                exit_fill = trade_sim.sl_fill(candle)
                current_trade.close(exit_fill)
                trades.append(current_trade)
                trades_taken += 1
                entry_fill = current_trade = None
                state = "IDLE" if trades_taken < config.MAX_TRADES_PER_LEG else "DONE"
            
            # IMMEDIATE KILL SWITCH: If we just exited a trade and this exact candle 
            # closed below BEP, kill the strike permanently for the day.
            if state in ("IDLE", "DONE") and bep_logic.closed_below(candle, bep_level):
                state = "DEAD"

        cells[key] = _board_cell(strike, leg, prev_state, state, bep_level,
                                 float(candle[4]), current_trade, trades_taken)

    return trades, cells


def _new_trade(strike, leg, branch_label, first_candle, entry_fill, trade_no, bep_level):
    return trade_sim.Trade(
        strike=strike, leg=leg, branch=branch_label,
        signal_time=_candle_key(first_candle), bep=round(float(bep_level), 2),
        entry=entry_fill, trade_no=trade_no,
    )


def _board_cell(strike, leg, prev_state, state, bep_level, close, trade, trades_taken):
    label = {
        "IDLE": "waiting", "ARM_NEXT_OPEN": "armed (open)",
        "PARKED": "parked (BEP+1)", "IN_TRADE": "in trade",
        "DEAD": "ignored", "DONE": "done",
    }.get(state, state)
    return {
        "key": f"{strike}{leg}",
        "strike": strike, "leg": leg, "bep": round(bep_level, 2),
        "close": round(close, 2), "state": state, "label": label,
        "in_trade": state == "IN_TRADE",
        "trades_taken": trades_taken,
        "entry_price": round(trade.entry.price, 2) if trade and trade.entry else None,
    }


def _resolve_beps(client, strikes, expiry, date_str, log_fn):
    ok_count = bep.prefetch_for_date(client, expiry, strikes, date_str)
    out = {}
    for s in strikes:
        key = (date_str, expiry, int(s))
        if key in bep._cache:
            out[s] = bep._cache[key]
    log_fn(f"BEP resolved for {ok_count}/{len(strikes)} strikes.")
    if not out:
        log_fn("No BEPs could be resolved (all PDC lookups failed).")
    return out


def _fetch_leg_candles(client, strikes, mapping, date_str, log_fn):
    tasks = []
    for strike in strikes:
        for opt in ("CE", "PE"):
            ik = (mapping.get(strike) or {}).get(opt)
            if ik:
                tasks.append((strike, opt, ik))

    def one(task):
        strike, opt, ik = task
        candles, _err = client.fetch_intraday_candles_for_day(
            ik, date_str, config.CANDLE_MINUTES)
        return (strike, opt), (candles or [])

    result = {}
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        for key, candles in ex.map(one, tasks):
            result[key] = candles
    log_fn(f"Fetched 5-min candles for {len(result)} legs.")
    return result


def _candle_key(candle) -> str:
    return candle[0][11:16]
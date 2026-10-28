"""
test_option_chain.py — standalone sanity check for the BEP Backtest project.

Verifies:
  1. Nifty LTP call works
  2. Nearest weekly expiry is returned
  3. `fetch_close_before` returns the correct PDC anchored to a past date
  4. `fetch_intraday_candles_for_day` returns candles for a past date
  5. Option contract lookup returns CE/PE instrument keys for a sample strike
"""
import config
import market_utils
from upstox_client import UpstoxClient


def main():
    if not config.UPSTOX_ACCESS_TOKEN:
        print("Set config.UPSTOX_ACCESS_TOKEN before running this test.")
        return

    client = UpstoxClient(config.UPSTOX_ACCESS_TOKEN)

    ltp_map, err = client.fetch_ltp([config.NIFTY_INDEX_KEY])
    if ltp_map is None:
        print(f"Nifty LTP fetch failed: {err}")
        return
    nifty_ltp = ltp_map.get(config.NIFTY_INDEX_KEY)
    print(f"Nifty LTP: {nifty_ltp}")

    expiry = market_utils.current_weekly_expiry(client)
    print(f"Nearest expiry: {expiry}")
    if not expiry:
        return

    mapping, err = market_utils.option_instrument_keys(client, expiry)
    if not mapping:
        print(f"Option contract lookup failed: {err}")
        return
    sample_strike = market_utils.nearest_strike(nifty_ltp)
    sample = mapping.get(sample_strike) or {}
    print(f"Sample strike {sample_strike}: {sample}")
    if not sample.get("CE"):
        return

    # PDC for a known past date (10 days before today)
    from datetime import datetime, timedelta
    past_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    pdc, err = client.fetch_close_before(sample["CE"], past_date)
    print(f"CE PDC before {past_date}: {pdc} ({err})")

    # 5-min candles for the same past date
    candles, err = client.fetch_intraday_candles_for_day(
        sample["CE"], past_date, config.CANDLE_MINUTES)
    n = len(candles) if candles else 0
    print(f"5-min candles for {past_date}: {n} bars ({err})")
    if candles:
        print(f"  first: {candles[0]}")
        print(f"  last : {candles[-1]}")


if __name__ == "__main__":
    main()
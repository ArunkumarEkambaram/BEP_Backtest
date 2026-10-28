"""
config.py — central configuration for the BEP Backtest app.
"""

# Nifty index instrument key (spot LTP / 5-min candles)
NIFTY_INDEX_KEY = "NSE_INDEX|Nifty 50"

# Underlying key used for option-chain / option-expiry / option-contract lookups
NIFTY_OPTION_UNDERLYING_KEY = "NSE_INDEX|Nifty 50"

STRIKE_INTERVAL = 50        # Nifty strike spacing

# Upstox — paste a pre-generated access token (or set it in the UI at runtime)
UPSTOX_ACCESS_TOKEN = ""

# ============================================================================
# BEP BACKTEST STRATEGY PARAMETERS
# ============================================================================
# Gap filter: at qualification (or a re-entry flip) a leg whose close is more
# than GAP_THRESHOLD points above BEP is parked for a limit entry at BEP+1
# instead of entering at the next candle's open.
GAP_THRESHOLD = 10

# Target in points from the entry price (intrabar fill when high >= entry+target).
TARGET_POINTS = 30

# How many candles a parked leg's BEP+1 limit stays live before the leg falls
# back to "keep waiting for a fresh touch + close-above flip".
PARK_CANDLES = 3

# Hard cap on entries per leg per day: the first entry plus one re-entry.
MAX_TRADES_PER_LEG = 2

# 5-minute candles on the 09:15 grid.
CANDLE_MINUTES = 5

# Strike universe for a backtest date = ATM +/- BEP_BAND_STRIKES strikes, where
# ATM = nearest strike to the 09:15 Nifty candle's OPEN on that date. The 09:15
# open is fixed the instant the candle opens, so no need to wait 5 minutes.
# 8 -> 17 strikes total (ATM + 8 above + 8 below) -> a fast, focused run.
# Set to None to fall back to "every strike Upstox returns for the expiry".
BEP_BAND_STRIKES = 8

# Market holidays as "YYYY-MM-DD" strings. The date picker excludes these
# dates. Empty by default — add dates here as you discover them (e.g. NSE
# Diwali/Republic Day closures). If you pick a holiday that isn't listed,
# the run fails cleanly with "No Nifty candles for <date> (holiday?)".
MARKET_HOLIDAYS = []
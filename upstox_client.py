"""
upstox_client.py — Upstox v2/v3 API wrapper for the BEP Backtest app.

Auth: paste in a pre-generated access_token; no OAuth flow.
"""
import requests
from urllib.parse import quote
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")

BASE_V2 = "https://api.upstox.com/v2"
BASE_V3 = "https://api.upstox.com/v3"


class UpstoxClient:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    # ---------------------------------------------------------- LTP
    def fetch_ltp(self, instrument_keys: list):
        """Returns ({instrument_key: ltp}, None) or (None, error_str)."""
        if not instrument_keys:
            return {}, None
        joined = ",".join(instrument_keys)
        url = f"{BASE_V2}/market-quote/ltp"
        try:
            resp = requests.get(url, headers=self.headers,
                                params={"instrument_key": joined}, timeout=10)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json().get("data", {})
            result = {}
            for v in data.values():
                ik = v.get("instrument_token") or v.get("instrument_key")
                ltp = v.get("last_price")
                if ik is not None and ltp is not None:
                    result[ik] = ltp
            return result, None
        except Exception as e:
            return None, str(e)

    # ---------------------------------------------------------- expiries
    def fetch_option_expiries(self, underlying_key: str):
        """Returns (list_of_expiry_date_strings_ascending, None) or (None, error)."""
        url = f"{BASE_V2}/option/contract"
        try:
            resp = requests.get(url, headers=self.headers,
                                params={"instrument_key": underlying_key}, timeout=10)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
            contracts = resp.json().get("data", [])
            expiries = sorted({c["expiry"] for c in contracts if c.get("expiry")})
            return expiries, None
        except Exception as e:
            return None, str(e)

    # ---------------------------------------------------------- option contracts
    def fetch_option_contracts(self, underlying_key: str, expiry_date: str = None):
        """
        Returns (contracts, None) or (None, error). Each contract dict includes
        instrument_key, strike_price, expiry, instrument_type ('CE'/'PE').
        """
        url = f"{BASE_V2}/option/contract"
        params = {"instrument_key": underlying_key}
        if expiry_date:
            params["expiry_date"] = expiry_date
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
            return resp.json().get("data", []), None
        except Exception as e:
            return None, str(e)

    # ---------------------------------------------------------- previous-day close (anchored)
    def fetch_close_before(self, instrument_key: str, before_date: str):
        """
        Close of the most recent daily candle dated STRICTLY BEFORE `before_date`
        (YYYY-MM-DD). Looks back 10 days so a weekend + holiday stretch is
        always covered. Returns (close, None) or (None, error).
        """
        encoded = quote(instrument_key, safe="")
        bd = datetime.strptime(before_date, "%Y-%m-%d")
        from_date = (bd - timedelta(days=10)).strftime("%Y-%m-%d")
        to_date = (bd - timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"{BASE_V3}/historical-candle/{encoded}/days/1/{to_date}/{from_date}"
        try:
            resp = requests.get(url, headers=self.headers, timeout=15)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
            candles = resp.json().get("data", {}).get("candles", [])
            for c in sorted(candles, key=lambda c: c[0], reverse=True):
                return c[4], None
            return None, "No daily candle in the look-back window"
        except Exception as e:
            return None, str(e)

    # ---------------------------------------------------------- intraday candles for a day
    def fetch_intraday_candles_for_day(self, instrument_key: str, date_str: str,
                                        interval_minutes: int = 5):
        """
        N-minute candles for a specific calendar date. Uses the historical
        endpoint for past dates and the intraday endpoint when date_str is today.
        Returns (candles_oldest_first, None) or (None, error).
        """
        encoded = quote(instrument_key, safe="")
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if date_str == today:
            url = f"{BASE_V3}/historical-candle/intraday/{encoded}/minutes/{interval_minutes}"
        else:
            url = (f"{BASE_V3}/historical-candle/{encoded}/minutes/{interval_minutes}"
                   f"/{date_str}/{date_str}")
        try:
            resp = requests.get(url, headers=self.headers, timeout=15)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
            candles = resp.json().get("data", {}).get("candles", [])
            return sorted(candles, key=lambda c: c[0]), None
        except Exception as e:
            return None, str(e)


def test_connection(access_token: str):
    """Quick sanity check the token works — hits the user profile endpoint."""
    url = f"{BASE_V2}/user/profile"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            return True, data.get("user_name", "Connected")
        return False, f"HTTP {resp.status_code}: {resp.text[:150]}"
    except Exception as e:
        return False, str(e)
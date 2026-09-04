"""Multi-provider data layer dengan fallback otomatis.

Provider candle (urutan prioritas):
  1. TwelveData    - 800 credits/hari free, sangat lengkap (forex/gold/indices)
  2. Alpha Vantage - 25 requests/hari free, forex + crypto + stocks (EOD untuk forex)

Fundamental:
  - Finnhub (DXY, US10Y, VIX, news) - 60 req/menit free

Penggunaan:
  candle = fetch_with_fallback(symbol="EURUSD", interval="5min", limit=200)
"""

import os
import time
import requests
import pandas as pd

# === Provider URLs ===
TWELVEDATA_URL = "https://api.twelvedata.com/time_series"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"


# === Interval mapping per provider ===
TWELVEDATA_INTERVAL = {
    "1min": "1min", "5min": "5min", "15min": "15min", "30min": "30min",
    "1h": "1h", "2h": "2h", "4h": "4h", "1day": "1day",
}

# Alpha Vantage mendukung: 1min, 5min, 15min, 30min, 60min, daily, weekly, monthly
ALPHA_INTERVAL = {
    "1min": "1min", "5min": "5min", "15min": "15min", "30min": "30min",
    "1h": "60min", "2h": None, "4h": None, "1day": "daily",
}

# Symbol mapping: TwelveData -> Alpha Vantage format
ALPHA_SYMBOL_MAP = {
    "EUR/USD": "EURUSD", "GBP/USD": "GBPUSD", "AUD/USD": "AUDUSD",
    "NZD/USD": "NZDUSD", "USD/JPY": "USDJPY", "USD/CHF": "USDCHF",
    "USD/CAD": "USDCAD", "EUR/JPY": "EURJPY", "GBP/JPY": "GBPJPY",
    "AUD/JPY": "AUDJPY", "NZD/JPY": "NZDJPY", "CAD/JPY": "CADJPY",
    "CHF/JPY": "CHFJPY", "EUR/GBP": "EURGBP", "EUR/AUD": "EURAUD",
    "EUR/CHF": "EURCHF", "EUR/CAD": "EURCAD", "GBP/AUD": "GBPAUD",
    "GBP/CAD": "GBPCAD", "GBP/CHF": "GBPCHF", "GBP/NZD": "GBPNZD",
    "XAU/USD": "XAUUSD", "XAG/USD": "XAGUSD",
}


def _df_from_twelvedata(data: dict) -> pd.DataFrame | None:
    """Parse response TwelveData -> DataFrame."""
    if data.get("status") == "error":
        return None
    values = data.get("values")
    if not values:
        return None
    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"], format="mixed", errors="coerce")
    df = df.dropna(subset=["datetime"])
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            return None
        df[col] = df[col].astype(float)
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def _df_from_alpha_vantage(data: dict) -> pd.DataFrame | None:
    """Parse response Alpha Vantage -> DataFrame."""
    if "Error Message" in data:
        return None
    if "Note" in data or "Information" in data:
        # Rate limit / informational messages
        return None

    # Cari key time series
    ts_key = None
    for key in data:
        if "Time Series" in key:
            ts_key = key
            break
    if not ts_key:
        return None

    series = data[ts_key]
    rows = []
    for ts, vals in series.items():
        try:
            rows.append({
                "datetime": pd.to_datetime(ts),
                "open": float(vals.get("1. open", 0)),
                "high": float(vals.get("2. high", 0)),
                "low": float(vals.get("3. low", 0)),
                "close": float(vals.get("4. close", 0)),
                "volume": float(vals.get("5. volume", 0) or 0),
            })
        except (ValueError, TypeError):
            continue
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def fetch_twelvedata(api_key: str, symbol: str, interval: str, limit: int,
                      timeout: int = 15) -> tuple[pd.DataFrame | None, str]:
    """Fetch candle dari TwelveData.

    Returns: (DataFrame or None, error_message)
    """
    try:
        params = {
            "symbol": symbol, "interval": interval, "outputsize": limit,
            "order": "ASC", "apikey": api_key,
        }
        r = requests.get(TWELVEDATA_URL, params=params, timeout=timeout)
        data = r.json()
        if data.get("status") == "error":
            return None, data.get("message", "unknown error")
        df = _df_from_twelvedata(data)
        if df is None:
            return None, "no data returned"
        return df, ""
    except Exception as e:
        return None, str(e)


def fetch_alpha_vantage(api_key: str, symbol: str, interval: str, limit: int,
                         timeout: int = 15) -> tuple[pd.DataFrame | None, str]:
    """Fetch candle dari Alpha Vantage (free tier: 25 req/hari).

    Returns: (DataFrame or None, error_message)
    """
    alpha_interval = ALPHA_INTERVAL.get(interval)
    if alpha_interval is None:
        return None, f"interval {interval} tidak didukung Alpha Vantage"

    alpha_symbol = ALPHA_SYMBOL_MAP.get(symbol, symbol.replace("/", ""))

    if alpha_interval == "daily":
        function = "FX_DAILY"
        params = {
            "function": function, "from_symbol": alpha_symbol[:3],
            "to_symbol": alpha_symbol[3:], "outputsize": "compact",
            "apikey": api_key,
        }
    else:
        function = "FX_INTRADAY"
        params = {
            "function": function, "interval": alpha_interval,
            "from_symbol": alpha_symbol[:3], "to_symbol": alpha_symbol[3:],
            "outputsize": "compact", "apikey": api_key,
        }

    try:
        r = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=timeout)
        data = r.json()
        df = _df_from_alpha_vantage(data)
        if df is None:
            msg = data.get("Note") or data.get("Information") or data.get("Error Message") or "no data"
            return None, msg
        if limit and len(df) > limit:
            df = df.tail(limit).reset_index(drop=True)
        return df, ""
    except Exception as e:
        return None, str(e)


def fetch_with_fallback(
    symbol: str,
    interval: str,
    limit: int = 200,
    twelvedata_key: str = "",
    alpha_vantage_key: str = "",
    prefer: str = "twelvedata",
) -> tuple[pd.DataFrame | None, str]:
    """Fetch candle dengan fallback otomatis.

    Returns: (DataFrame or None, provider_used_or_error)
    """
    errors = []

    if prefer == "alpha_vantage" and alpha_vantage_key:
        df, err = fetch_alpha_vantage(alpha_vantage_key, symbol, interval, limit)
        if df is not None:
            return df, "alpha_vantage"
        errors.append(f"alpha_vantage: {err}")

    if twelvedata_key:
        df, err = fetch_twelvedata(twelvedata_key, symbol, interval, limit)
        if df is not None:
            return df, "twelvedata"
        errors.append(f"twelvedata: {err}")

    if prefer != "alpha_vantage" and alpha_vantage_key:
        df, err = fetch_alpha_vantage(alpha_vantage_key, symbol, interval, limit)
        if df is not None:
            return df, "alpha_vantage"
        errors.append(f"alpha_vantage: {err}")

    return None, " | ".join(errors) if errors else "no API key configured"

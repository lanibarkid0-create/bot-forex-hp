"""High-Probability Forex Analyzer - ICT/SMC + Multi-TF + News + Session + Range Filter.

Layer konfirmasi:
1. HTF Bias (H4/H1) - trend utama
2. LTF Structure (M15) - pullback ke OB/FVG
3. LTF Entry (M5) - rejection confirmation
4. Session filter (London/NY killzone)
5. Range filter (ADX check)
6. Confluence score (minimum 7/10 untuk entry)
"""

import re
import math
import time
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from fundamental import (
    fetch_forexfactory_calendar, is_news_window, get_upcoming_news,
    calc_currency_strength, strength_label, strength_emoji,
    get_pair_interest_diff, format_fundamental_block,
)
from indicators import (
    compute_rsi, detect_rsi_divergence, rsi_signal,
    compute_macd, macd_signal,
    compute_bollinger, bollinger_signal, detect_bb_squeeze,
    compute_stoch_rsi, stoch_rsi_signal,
    compute_vwap, vwap_signal,
    compute_atr, atr_percent,
    multi_indicator_confluence,
)

# === SYMBOL MAP ===
SYMBOL_MAP = {
    # Forex majors
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "AUDUSD": "AUD/USD", "NZDUSD": "NZD/USD",
    "USDJPY": "USD/JPY", "USDCHF": "USD/CHF", "USDCAD": "USD/CAD",
    # Forex crosses
    "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY", "AUDJPY": "AUD/JPY", "NZDJPY": "NZD/JPY",
    "CADJPY": "CAD/JPY", "CHFJPY": "CHF/JPY",
    "EURGBP": "EUR/GBP", "EURAUD": "EUR/AUD", "EURCHF": "EUR/CHF", "EURCAD": "EUR/CAD",
    "GBPAUD": "GBP/AUD", "GBPCAD": "GBP/CAD", "GBPCHF": "GBP/CHF", "GBPNZD": "GBP/NZD",
    "AUDCAD": "AUD/CAD", "AUDCHF": "AUD/CHF", "AUDNZD": "AUD/NZD",
    "CADCHF": "CAD/CHF", "NZDCAD": "NZD/CAD", "NZDCHF": "NZD/CHF",
    "EURNZD": "EUR/NZD",
    # Metals
    "XAUUSD": "XAU/USD", "XAU": "XAU/USD", "GOLD": "XAU/USD",
    "XAGUSD": "XAG/USD", "XAG": "XAG/USD", "SILVER": "XAG/USD",
    # Oil
    "XTIUSD": "CL", "XTI": "CL", "OIL": "CL", "WTI": "CL", "CL": "CL",
    # Indices
    "NAS100": "NDX", "US100": "NDX", "NQ": "NDX", "NDX": "NDX",
    "US30": "DJI", "DJI": "DJI", "DOW": "DJI", "DJIA": "DJI",
    "SPX500": "SPX", "SP500": "SPX", "SPX": "SPX", "ES": "SPX",
    "DAX": "DAX", "GER40": "DAX", "DE40": "DAX",
    "FTSE": "FTSE", "UK100": "FTSE", "UKX": "FTSE",
    "NIKKEI": "N225", "N225": "N225", "JPN225": "N225", "JP225": "N225",
    # Commodities
    "NATGAS": "NG", "NG": "NG", "NATURALGAS": "NG", "GAS": "NG",
    "BRENT": "BRN", "BRN": "BRN", "UKOIL": "BRN",
    "COPPER": "HG", "HG": "HG", "XCU": "HG",
    "WHEAT": "ZW", "ZW": "ZW", "CORN": "ZC", "ZC": "ZC",
    "BTC": "BTC/USD", "ETH": "ETH/USD",
}

# === TIMEFRAME MAP ===
TF_MAP = {
    "M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "M45": "45min",
    "H1": "1h", "H2": "2h", "H4": "4h", "H8": "8h",
    "D1": "1day", "W1": "1week", "MN": "1month",
}

SUPPORTED_TF = ["M1", "M5", "M15", "M30", "M45", "H1", "H2", "H4", "H8", "D1", "W1", "MN"]

# Default pair list untuk multi-pair scanner
DEFAULT_SCAN_PAIRS = [
    # Forex majors
    "EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCHF", "USDCAD",
    # Forex crosses (most traded)
    "EURJPY", "GBPJPY", "AUDJPY", "EURGBP", "GBPAUD",
    # Metals
    "XAUUSD", "XAGUSD",
    # Indices
    "NAS100", "US30", "SPX500", "DAX", "FTSE", "NIKKEI",
    # Commodities
    "OIL", "NATGAS",
]

# === SESSION / KILLZONE (UTC) ===
KILLZONES = {
    "london": {"start": 1, "end": 4, "name": "London Killzone"},
    "newyork": {"start": 8, "end": 11, "name": "New York Killzone"},
    "london_ny": {"start": 13, "end": 16, "name": "London-NY Overlap"},
}

# === HTTP SESSION (connection pooling, reuse TCP) ===
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "forex-bot/1.0"})
# Connection pool: reuse TCP connection untuk speed
# Max ~20 koneksi paralel (6 TF + 8 currency strength + slack)
adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30)
_SESSION.mount("https://", adapter)

# === CANDLE CACHE (TTL 60 detik) ===
_CANDLE_CACHE: dict[tuple, tuple[float, "pd.DataFrame"]] = {}
_CACHE_TTL = 60  # seconds

# === NEWS DATES (high-impact events) ===
# Format: (date_str, time_utc, event, currency)
# Auto-cached per day
NEWS_EVENTS_CACHE = {"date": None, "events": []}


def parse_user_input(text: str) -> tuple[str, str] | None:
    """Parse 'XAUUSD M5' / 'GBPJPY H1' / 'EURUSD' (default M5)."""
    text = text.strip().upper()
    tf_pattern = "|".join(SUPPORTED_TF)
    m = re.match(rf"^([A-Z][A-Z0-9]{{2,7}})(?:\s+({tf_pattern}))?$", text)
    if not m:
        return None
    sym = m.group(1)
    tf = m.group(2) or "M5"
    if sym not in SYMBOL_MAP:
        return None
    return SYMBOL_MAP[sym], tf


def fetch_candles(api_key: str, symbol: str, interval: str, limit: int = 200,
                   max_retries: int = 3) -> pd.DataFrame:
    """Fetch candle dari Twelve Data dengan cache + retry + rate-limit handling.

    Free tier: 8 API credits/menit. Retry otomatis kalau kena rate limit.
    """
    cache_key = (api_key[:8], symbol, interval, limit)
    now = time.time()
    cached = _CANDLE_CACHE.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1].copy()

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol, "interval": interval, "outputsize": limit,
        "order": "ASC", "apikey": api_key,
    }

    last_error = None
    for attempt in range(max_retries):
        try:
            r = _SESSION.get(url, params=params, timeout=20)
            data = r.json()

            # Cek error
            if data.get("status") == "error":
                msg = data.get("message", "API error")
                last_error = msg
                # Rate limit → tunggu 60 detik
                if "credits" in msg.lower() or "rate" in msg.lower() or "limit" in msg.lower():
                    wait = 60
                    time.sleep(wait)
                    continue
                # Symbol butuh plan upgrade
                if "plan" in msg.lower() or "grow" in msg.lower() or "venture" in msg.lower():
                    raise SymbolPlanError(symbol, msg)
                # Symbol tidak ditemukan
                if "not found" in msg.lower() or "symbol" in msg.lower():
                    raise SymbolNotFoundError(symbol, msg)
                raise RuntimeError(msg)

            values = data.get("values")
            if not values:
                raise RuntimeError(f"No data for {symbol} {interval}")

            df = pd.DataFrame(values)
            df["datetime"] = pd.to_datetime(df["datetime"], format="mixed", errors="coerce")
            df = df.dropna(subset=["datetime"])
            for col in ("open", "high", "low", "close"):
                df[col] = df[col].astype(float)
            df = df.sort_values("datetime").reset_index(drop=True)
            _CANDLE_CACHE[cache_key] = (now, df)
            return df.copy()

        except (SymbolPlanError, SymbolNotFoundError):
            raise
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # exponential backoff
                continue

    raise RuntimeError(f"Fetch gagal setelah {max_retries} attempt: {last_error}")


def fetch_candles_sequential(api_key: str, symbol: str, specs: list[tuple[str, int]],
                              delay: float = 1.0) -> dict[str, pd.DataFrame]:
    """Fetch multiple timeframe SEQUENTIAL dengan delay aman untuk free tier.

    Free tier TwelveData = 8 credits/menit → jeda 8 detik aman.
    Sequential = pasti dapat semua data, tidak ada rate limit hit.
    """
    results = {}
    for i, (interval, limit) in enumerate(specs):
        if i > 0:
            time.sleep(delay)
        try:
            results[interval] = fetch_candles(api_key, symbol, interval, limit)
        except Exception as e:
            results[interval] = None
    return results


def fetch_candles_parallel(api_key: str, symbol: str, specs: list[tuple[str, int]],
                            max_workers: int = 2, delay: float = 0.5) -> dict[str, pd.DataFrame]:
    """Fetch multiple timeframe parallel dengan throttle + delay awal.

    specs: list of (interval, limit) tuples
    max_workers: max concurrent request (default 2, aman untuk free tier 8 req/menit)
    delay: jeda awal antar request
    """
    results = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(specs))) as ex:
        futures = {
            ex.submit(fetch_candles, api_key, symbol, interval, limit): interval
            for interval, limit in specs
        }
        for fut in as_completed(futures):
            interval = futures[fut]
            try:
                results[interval] = fut.result()
            except Exception as e:
                results[interval] = None
    return results


# === Custom exceptions ===
class SymbolPlanError(Exception):
    """Symbol butuh plan upgrade (Grow/Venture/Pro)."""
    def __init__(self, symbol, msg):
        self.symbol = symbol
        self.msg = msg
        super().__init__(f"{symbol}: {msg}")


class SymbolNotFoundError(Exception):
    """Symbol tidak ditemukan di TwelveData."""
    def __init__(self, symbol, msg):
        self.symbol = symbol
        self.msg = msg
        super().__init__(f"{symbol}: {msg}")


# === ICT/SMC FUNCTIONS ===

def get_market_structure(df: pd.DataFrame) -> dict:
    """Detect swing structure, trend, CHoCH, BOS (NUMPY vectorized, ~5x lebih cepat)."""
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    n = len(df)
    if n < 3:
        return {"trend": "neutral", "choch": None, "choch_idx": None, "bos": None,
                "swing_highs": [], "swing_lows": []}

    # Vectorized swing detection
    is_swing_high = (highs[1:-1] > highs[:-2]) & (highs[1:-1] > highs[2:])
    is_swing_low = (lows[1:-1] < lows[:-2]) & (lows[1:-1] < lows[2:])

    swing_highs = (np.where(is_swing_high)[0] + 1).tolist()
    swing_lows = (np.where(is_swing_low)[0] + 1).tolist()

    trend = "neutral"
    if len(swing_highs) > 1 and len(swing_lows) > 1:
        hh = highs[swing_highs[-1]] > highs[swing_highs[-2]]
        hl = lows[swing_lows[-1]] > lows[swing_lows[-2]]
        lh = highs[swing_highs[-1]] < highs[swing_highs[-2]]
        ll = lows[swing_lows[-1]] < lows[swing_lows[-2]]
        if hh and hl:
            trend = "bullish"
        elif lh and ll:
            trend = "bearish"

    choch = None
    choch_idx = None
    if trend == "bullish" and len(swing_lows) >= 2:
        if lows[swing_lows[-1]] > lows[swing_lows[-2]]:
            choch = "bullish"
            choch_idx = swing_lows[-1]
    elif trend == "bearish" and len(swing_highs) >= 2:
        if highs[swing_highs[-1]] < highs[swing_highs[-2]]:
            choch = "bearish"
            choch_idx = swing_highs[-1]

    bos = None
    if len(swing_highs) >= 2 and highs[swing_highs[-1]] > highs[swing_highs[-2]]:
        bos = "bullish"
    if len(swing_lows) >= 2 and lows[swing_lows[-1]] < lows[swing_lows[-2]]:
        bos = "bearish" if bos is None else bos

    return {"trend": trend, "choch": choch, "choch_idx": choch_idx, "bos": bos,
            "swing_highs": swing_highs, "swing_lows": swing_lows}


def detect_fvg(df: pd.DataFrame) -> list[dict]:
    """Detect Fair Value Gaps (vectorized)."""
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    n = len(df)
    if n < 3:
        return []
    # Bullish FVG: low[i-1] > high[i-2] (gap up antara candle i-2 dan i)
    # Bearish FVG: high[i-1] < low[i-2] (gap down)
    bull_mask = lows[1:-1] > highs[:-2]
    bear_mask = highs[1:-1] < lows[:-2]
    bull_idx = np.where(bull_mask)[0] + 1  # candle_idx = i-1
    bear_idx = np.where(bear_mask)[0] + 1

    fvgs = []
    for i in bull_idx:
        fvgs.append({"type": "bullish", "low": lows[i - 1], "high": highs[i - 2], "candle_idx": i - 2})
    for i in bear_idx:
        fvgs.append({"type": "bearish", "high": highs[i - 1], "low": lows[i - 2], "candle_idx": i - 2})
    return fvgs


def detect_order_blocks(df: pd.DataFrame) -> list[dict]:
    """Detect Order Blocks (vectorized)."""
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    opens = df["open"].values.astype(float)
    closes = df["close"].values.astype(float)
    n = len(df)
    if n < 3:
        return []
    # Bullish OB: candle i bearish (close<open) + next candle bullish
    # Bearish OB: candle i bullish (close>open) + next candle bearish
    is_bearish = closes < opens
    is_bullish = closes > opens
    bull_ob_mask = is_bearish[:-1] & is_bullish[1:]
    bear_ob_mask = is_bullish[:-1] & is_bearish[1:]
    bull_idx = np.where(bull_ob_mask)[0]
    bear_idx = np.where(bear_ob_mask)[0]

    obses = []
    for i in bull_idx:
        obses.append({"type": "bullish", "price": opens[i], "high": highs[i], "low": lows[i], "candle_idx": i})
    for i in bear_idx:
        obses.append({"type": "bearish", "price": opens[i], "high": highs[i], "low": lows[i], "candle_idx": i})
    return obses


def detect_liquidity(df: pd.DataFrame) -> dict:
    """Detect BSL/SSL levels (vectorized)."""
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    n = len(df)
    if n < 3:
        return {"ssl_price": None, "bsl_price": None, "swing_lows": [], "swing_highs": []}
    is_swing_high = (highs[1:-1] > highs[:-2]) & (highs[1:-1] > highs[2:])
    is_swing_low = (lows[1:-1] < lows[:-2]) & (lows[1:-1] < lows[2:])
    sh = (np.where(is_swing_high)[0] + 1).tolist()
    sl = (np.where(is_swing_low)[0] + 1).tolist()
    return {"ssl_price": float(lows[sl].min()) if sl else None,
            "bsl_price": float(highs[sh].max()) if sh else None,
            "swing_lows": sl, "swing_highs": sh}


def is_mitigated_fvg(fvg: dict, df: pd.DataFrame) -> bool:
    idx = fvg["candle_idx"]
    if fvg["type"] == "bullish":
        return any(df["low"].iloc[i] < fvg["low"] for i in range(idx + 3, len(df)))
    return any(df["high"].iloc[i] > fvg["high"] for i in range(idx + 3, len(df)))


def is_mitigated_ob(ob: dict, df: pd.DataFrame) -> bool:
    idx = ob["candle_idx"]
    if ob["type"] == "bullish":
        return any(df["low"].iloc[i] < ob["low"] for i in range(idx + 1, len(df)))
    return any(df["high"].iloc[i] > ob["high"] for i in range(idx + 1, len(df)))


def compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Hitung ADX (Average Directional Index) - untuk range filter."""
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)
    if n < period + 1:
        return 0.0

    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if up > down and up > 0 else 0
        minus_dm[i] = down if down > up and down > 0 else 0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))

    # Smoothed
    atr = pd.Series(tr).rolling(period).mean().values
    plus_di = 100 * pd.Series(plus_dm).rolling(period).mean().values / np.where(atr == 0, 1, atr)
    minus_di = 100 * pd.Series(minus_dm).rolling(period).mean().values / np.where(atr == 0, 1, atr)
    dx = 100 * np.abs(plus_di - minus_di) / np.where(plus_di + minus_di == 0, 1, plus_di + minus_di)
    adx = pd.Series(dx).rolling(period).mean().iloc[-1]
    return float(adx) if not np.isnan(adx) else 0.0


# === SESSION / KILLZONE ===

def get_session() -> dict:
    """Get current session UTC."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    session = "off"
    in_killzone = False
    kz_name = None
    for kz_key, kz in KILLZONES.items():
        if kz["start"] <= hour < kz["end"]:
            session = kz_key
            in_killzone = True
            kz_name = kz["name"]
            break
    return {"session": session, "in_killzone": in_killzone, "kz_name": kz_name, "hour_utc": hour}


# === NEWS FILTER ===

# Jadwal high-impact news manual (update mingguan)
# Format: [(date, time_utc, event, currency, impact)]
HIGH_IMPACT_NEWS = [
    # Format ISO date
    # ("2026-08-28", "12:30", "CPI m/m", "USD", "high"),
]


def fetch_news_calendar() -> list[dict]:
    """Fetch high-impact news dari ForexFactory RSS (simplified).
    Returns list of events today dalam format {time_utc, event, currency, impact}.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if NEWS_EVENTS_CACHE["date"] == today and NEWS_EVENTS_CACHE["events"]:
        return NEWS_EVENTS_CACHE["events"]

    events = []
    # ForexFactory calendar via JSON endpoint (public)
    try:
        url = f"https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for ev in data:
                if ev.get("impact") in ("High", "Holiday"):
                    date_str = ev.get("date", "")
                    if today in date_str:
                        events.append({
                            "time_utc": ev.get("time", ""),
                            "event": ev.get("title", ""),
                            "currency": ev.get("country", ""),
                            "impact": ev.get("impact", ""),
                        })
    except Exception:
        pass

    NEWS_EVENTS_CACHE["date"] = today
    NEWS_EVENTS_CACHE["events"] = events
    return events


def is_news_window(buffer_min: int = 30) -> tuple[bool, str]:
    """Cek apakah sekarang dalam window high-impact news (30 menit sebelum/sesudah)."""
    events = fetch_news_calendar()
    if not events:
        return False, ""
    now = datetime.now(timezone.utc)
    for ev in events:
        try:
            # Parse time
            ev_time = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {ev['time_utc']}", "%Y-%m-%d %H:%M")
            ev_time = ev_time.replace(tzinfo=timezone.utc)
            diff_min = abs((now - ev_time).total_seconds() / 60)
            if diff_min <= buffer_min:
                return True, f"{ev['currency']} {ev['event']} ({ev['time_utc']} UTC)"
        except Exception:
            continue
    return False, ""


# === CONFLUENCE SCORING ===

def score_setup(
    h4_trend: str,
    h1_trend: str,
    m15_struct: dict,
    m5_struct: dict,
    entry_type: str,
    is_killzone: bool,
    adx: float,
    in_news: bool,
    ohlc_15m: pd.Series = None,
) -> dict:
    """Hitung confluence score 0-10. Minimum 7 untuk entry.

    Layers:
    - HTF bias alignment (3 pts)
    - LTF structure confirmation (2 pts)
    - Entry at OB/FVG (2 pts)
    - Killzone timing (1 pt)
    - Trending market (1 pt)
    - No news (1 pt)
    """
    score = 0
    breakdown = []

    # Layer 1: HTF alignment (3 pts)
    if h4_trend == h1_trend and h4_trend in ("bullish", "bearish"):
        score += 3
        breakdown.append(f"✓ HTF aligned {h4_trend.upper()} (+3)")
    elif h4_trend in ("bullish", "bearish"):
        score += 2
        breakdown.append(f"~ HTF partial {h4_trend.upper()} (+2)")
    else:
        breakdown.append("✗ HTF not aligned (+0)")

    # Layer 2: LTF structure (2 pts)
    if m15_struct["choch"] is not None and m15_struct["choch_idx"] is not None:
        bars_ago = 100 - 1 - m15_struct["choch_idx"]  # rough estimate
        if bars_ago < 30:
            score += 2
            breakdown.append(f"✓ Recent CHoCH {m15_struct['choch']} (+2)")
        else:
            score += 1
            breakdown.append(f"~ Old CHoCH {m15_struct['choch']} (+1)")
    elif m15_struct["bos"] is not None:
        score += 1
        breakdown.append(f"~ BOS {m15_struct['bos']} (+1)")

    # Layer 3: Entry at OB/FVG (2 pts)
    if entry_type in ("OB", "FVG"):
        score += 2
        breakdown.append(f"✓ Entry at {entry_type} (+2)")
    else:
        breakdown.append(f"~ Entry type {entry_type} (+0)")

    # Layer 4: Killzone (1 pt)
    if is_killzone:
        score += 1
        breakdown.append("✓ In killzone (+1)")

    # Layer 5: Trending (1 pt)
    if adx > 20:
        score += 1
        breakdown.append(f"✓ Trending ADX {adx:.1f} (+1)")
    else:
        breakdown.append(f"✗ Ranging ADX {adx:.1f} (+0)")

    # Layer 6: No news (1 pt)
    if not in_news:
        score += 1
        breakdown.append("✓ No news window (+1)")
    else:
        breakdown.append("✗ News window (+0)")

    return {"score": score, "breakdown": breakdown, "high_prob": score >= 7}


# === MAIN ANALYSIS ===

def get_zone_width(price: float, mode: str = "intraday") -> float:
    """Adaptive zone width:
    - scalping  : 5 pips (tight)
    - intraday  : 10 pips (default)
    - swing     : 30 pips (wide)
    - XAUUSD: 1.0 / JPY: 0.10 / Major forex: 0.001
    """
    # Base pips per mode
    pips_map = {"scalping": 5, "intraday": 10, "swing": 30}
    pips = pips_map.get(mode, 10)

    if price > 1000:  # XAUUSD, XAGUSD, oil
        return float(pips)  # 1 pip XAU ≈ $0.01, 5 pips = $0.05
    elif price > 50:  # JPY pairs
        return pips * 0.01  # 1 pip JPY = 0.01
    else:  # Major & cross forex
        return max(0.0005, price * 0.0001 * pips)  # 1 pip ≈ 0.0001 dari price


def analyze_full(api_key: str, symbol: str, timeframe: str = "M5", mode: str = "intraday") -> dict:
    """High-probability analysis dengan 6-timeframe confluence (D1/H4/H1/M30/M15/M5).

    Args:
        api_key: TwelveData API key
        symbol: trading pair (e.g. EURUSD, XAUUSD, NAS100)
        timeframe: entry timeframe (M5 recommended)
        mode: 'scalping' (M5-only entry, tighter SL, 5-15 pips TP)
              'intraday' (multi-TF, standard SL/TP, 10-30 pips)
              'swing' (HTF-only, wider SL/TP, 50-150 pips)

    Returns dict dengan signal/score/entry_zone/sl_zone/tp_zones/multi-TF trends dll.
    """
    td_sym = SYMBOL_MAP.get(symbol.upper(), symbol)
    td_tf = TF_MAP.get(timeframe, "5min")

    # === MULTI-TIMEFRAME FETCH (parallel 3 workers, ~1.5s total) ===
    # HTF (D1, H4) → trend utama
    # MTF (H1, M30) → pullback zone
    # LTF (M15) → struktur
    # Entry TF (M5) → konfirmasi rejection
    specs = [
        (td_tf, 200),     # Entry TF
        ("5min", 200),    # M5 confirmation
        ("15min", 200),   # M15 structure
        ("30min", 200),   # M30 pullback
        ("1h", 200),      # H1 bias
        ("4h", 100),      # H4 trend
        ("1day", 100),    # D1 trend utama
    ]
    try:
        # Parallel 3 workers → 6 req paralel selesai dalam ~1.5s
        # 3 worker aman untuk free tier (8/menit, max burst ~6 dalam sekejap OK)
        fetched = fetch_candles_parallel(api_key, td_sym, specs, max_workers=3, delay=0.2)
    except SymbolPlanError as e:
        raise SymbolPlanError(symbol, f"'{symbol}' butuh plan Grow/Venture di TwelveData. Coba pair forex (EURUSD, XAUUSD) yang free.")
    except SymbolNotFoundError as e:
        raise SymbolNotFoundError(symbol, f"'{symbol}' tidak ditemukan di TwelveData.")

    df = fetched.get(td_tf)
    df_m5 = fetched.get("5min")
    df_m15 = fetched.get("15min")
    df_m30 = fetched.get("30min")
    df_h1 = fetched.get("1h")
    df_h4 = fetched.get("4h")
    df_d1 = fetched.get("1day")
    if df is None or df_m5 is None or df_m15 is None or df_h1 is None or df_h4 is None or df_d1 is None:
        failed = [tf for tf, df_v in zip([td_tf, "5min", "15min", "30min", "1h", "4h", "1day"], [df, df_m5, df_m15, df_m30, df_h1, df_h4, df_d1]) if df_v is None]
        raise RuntimeError(f"Gagal fetch {symbol} di TF: {', '.join(failed)}")

    price = float(df["close"].iloc[-1])

    # Multi-TF structure (6 timeframe)
    ms_d1 = get_market_structure(df_d1)
    ms_h4 = get_market_structure(df_h4)
    ms_h1 = get_market_structure(df_h1)
    ms_m30 = get_market_structure(df_m30)
    ms_m15 = get_market_structure(df_m15)
    ms_m5 = get_market_structure(df_m5)

    # === DECIDE BIAS (HTF + MTF voting, BUKAN M5) ===
    # Multi-TF = untuk ANALISA BIAS saja (D1, H4, H1, M30, M15)
    # M5 = STRICT untuk entry confirmation (CHoCH, OB, FVG, SL, TP)
    d1_trend = ms_d1["trend"]
    h4_trend = ms_h4["trend"]
    h1_trend = ms_h1["trend"]
    m30_trend = ms_m30["trend"]
    m15_trend = ms_m15["trend"]
    m5_trend = ms_m5["trend"]  # info only, TIDAK masuk voting

    # Voting: D1=3, H4=3, H1=2, M30=1, M15=1 (HTF dominan, M5 excluded)
    votes = {"bullish": 0, "bearish": 0, "neutral": 0}
    for trend, weight in [(d1_trend, 3), (h4_trend, 3), (h1_trend, 2), (m30_trend, 1), (m15_trend, 1)]:
        votes[trend] = votes.get(trend, 0) + weight

    if votes["bullish"] > votes["bearish"] and votes["bullish"] >= 3:
        bias = "bullish"
    elif votes["bearish"] > votes["bullish"] and votes["bearish"] >= 3:
        bias = "bearish"
    else:
        bias = "neutral"

    # M5 STRICT KONFIRMASI: butuh CHoCH searah bias di M5 untuk entry
    # - bullish bias + M5 CHoCH bullish → BUY signal
    # - bearish bias + M5 CHoCH bearish → SELL signal
    # - else WAIT (tunggu CHoCH confirm)
    m5_choch = ms_m5.get("choch")
    if bias == "bullish" and m5_choch == "bullish":
        signal = "BUY"
    elif bias == "bearish" and m5_choch == "bearish":
        signal = "SELL"
    elif bias != "neutral" and ms_m5.get("bos") == bias:
        # BOS searah tanpa CHoCH = weaker entry
        signal = "BUY" if bias == "bullish" else "SELL"
    else:
        signal = "WAIT"

    # === ENTRY ZONE (STRICT M5) ===
    # Deteksi OB/FVG di M5 saja (low TF untuk entry)
    # Validasi: zone harus searah bias, di bawah/atas price (discount/premium), belum dimitigasi
    fvgs_m5 = [f for f in detect_fvg(df) if not is_mitigated_fvg(f, df) and f["candle_idx"] >= len(df) - 30]
    obses_m5 = [o for o in detect_order_blocks(df) if not is_mitigated_ob(o, df) and o["candle_idx"] >= len(df) - 30]
    liq_m5 = detect_liquidity(df)

    entry_zone = None
    entry_zone_full = None  # full OB/FVG range (sebelum shrink)
    sl_zone = None
    tp_zones = []
    entry_type = "none"
    zw = get_zone_width(price, mode)

    def shrink(low, high):
        """Shrink zone jadi lebih presisi (mid ± zw/2)."""
        mid = (low + high) / 2
        return {"low": mid - zw / 2, "high": mid + zw / 2}

    if signal == "BUY":
        # Cari bullish OB/FVG di BAWAH price (discount zone)
        bull_obs = [o for o in obses_m5 if o["type"] == "bullish" and o["high"] < price]
        bull_fvgs = [f for f in fvgs_m5 if f["type"] == "bullish" and f["high"] < price]
        if bull_obs:
            ob = bull_obs[-1]  # OB terakhir
            entry_zone_full = {"low": ob["low"], "high": ob["high"]}
            entry_zone = shrink(ob["low"], ob["high"])
            entry_type = "OB"
        elif bull_fvgs:
            fvg = bull_fvgs[-1]
            entry_zone_full = {"low": fvg["low"], "high": fvg["high"]}
            entry_zone = shrink(fvg["low"], fvg["high"])
            entry_type = "FVG"
        elif ms_m5["swing_lows"]:
            sl_price = float(df["low"].iloc[ms_m5["swing_lows"][-1]])
            entry_zone_full = {"low": sl_price, "high": sl_price}
            entry_zone = shrink(sl_price - abs(price) * 0.0005, sl_price + abs(price) * 0.0005)
            entry_type = "swing_low"
    elif signal == "SELL":
        # Cari bearish OB/FVG di ATAS price (premium zone)
        bear_obs = [o for o in obses_m5 if o["type"] == "bearish" and o["low"] > price]
        bear_fvgs = [f for f in fvgs_m5 if f["type"] == "bearish" and f["low"] > price]
        if bear_obs:
            ob = bear_obs[-1]
            entry_zone_full = {"low": ob["low"], "high": ob["high"]}
            entry_zone = shrink(ob["low"], ob["high"])
            entry_type = "OB"
        elif bear_fvgs:
            fvg = bear_fvgs[-1]
            entry_zone_full = {"low": fvg["low"], "high": fvg["high"]}
            entry_zone = shrink(fvg["low"], fvg["high"])
            entry_type = "FVG"
        elif ms_m5["swing_highs"]:
            sh_price = float(df["high"].iloc[ms_m5["swing_highs"][-1]])
            entry_zone_full = {"low": sh_price, "high": sh_price}
            entry_zone = shrink(sh_price - abs(price) * 0.0005, sh_price + abs(price) * 0.0005)
            entry_type = "swing_high"

    # === SL & TP (STRICT M5 swing high/low) ===
    # SL = swing low/high M5 di bawah/atas entry (low TF)
    # TP = swing high/low M5 di atas/bawah entry (low TF) + RR ratio fallback
    if entry_zone and signal != "WAIT":
        entry_mid = (entry_zone["low"] + entry_zone["high"]) / 2
        sl_pct = {"scalping": 0.005, "intraday": 0.01, "swing": 0.03}.get(mode, 0.01)
        max_sl_dist = abs(price) * sl_pct
        rr_set = {"scalping": [1.0, 1.5, 2.0], "intraday": [1.0, 1.5, 3.0], "swing": [2.0, 3.0, 5.0]}.get(mode, [1.0, 1.5, 3.0])
        tp_labels = ["TP1", "TP2", "TP3"]

        if signal == "BUY":
            # === SL: cari swing low M5 di BAWAH entry ===
            sl_candidates = []
            for idx in ms_m5["swing_lows"]:
                sw_low = float(df["low"].iloc[idx])
                if sw_low < entry_zone["low"] and (entry_zone["low"] - sw_low) <= max_sl_dist:
                    sl_candidates.append(sw_low)
            if liq_m5["ssl_price"] and liq_m5["ssl_price"] < entry_zone["low"] and (entry_zone["low"] - liq_m5["ssl_price"]) <= max_sl_dist:
                sl_candidates.append(liq_m5["ssl_price"])
            sl_ref = min(sl_candidates) if sl_candidates else (entry_zone["low"] - abs(price) * sl_pct / 2)

            sl_mid = sl_ref - abs(price) * 0.0002
            sl_zone = {"low": sl_mid - zw / 2, "high": sl_mid + zw / 2}
            risk = entry_mid - sl_zone["high"]
            if risk > 0:
                # === TP: cari swing high M5 di ATAS entry sebagai target ===
                tp_candidates = []
                for idx in ms_m5["swing_highs"]:
                    sh = float(df["high"].iloc[idx])
                    if sh > entry_zone["high"]:
                        # Hitung RR natural ke swing high ini
                        natural_rr = (sh - entry_mid) / risk
                        if natural_rr >= rr_set[0]:  # minimal RR TP1
                            tp_candidates.append((sh, natural_rr))
                tp_candidates.sort(key=lambda x: x[1])  # sort by RR

                # Bangun TP zones: prefer swing high M5, fallback ke RR ratio
                tp_zones = []
                for i, (rr_target, label) in enumerate(zip(rr_set, tp_labels)):
                    if i < len(tp_candidates):
                        sh, _ = tp_candidates[i]
                        tp_zones.append({**shrink(sh - zw / 2, sh + zw / 2), "rr": round((sh - entry_mid) / risk, 2), "label": label, "source": "M5 swing"})
                    else:
                        # Fallback ke RR-based
                        tp_zones.append({**shrink(entry_mid + risk * rr_target - zw / 2, entry_mid + risk * rr_target + zw / 2), "rr": rr_target, "label": label, "source": "RR ratio"})

        else:  # SELL
            # === SL: cari swing high M5 di ATAS entry ===
            sl_candidates = []
            for idx in ms_m5["swing_highs"]:
                sw_high = float(df["high"].iloc[idx])
                if sw_high > entry_zone["high"] and (sw_high - entry_zone["high"]) <= max_sl_dist:
                    sl_candidates.append(sw_high)
            if liq_m5["bsl_price"] and liq_m5["bsl_price"] > entry_zone["high"] and (liq_m5["bsl_price"] - entry_zone["high"]) <= max_sl_dist:
                sl_candidates.append(liq_m5["bsl_price"])
            sl_ref = max(sl_candidates) if sl_candidates else (entry_zone["high"] + abs(price) * sl_pct / 2)

            sl_mid = sl_ref + abs(price) * 0.0002
            sl_zone = {"low": sl_mid - zw / 2, "high": sl_mid + zw / 2}
            risk = sl_zone["low"] - entry_mid
            if risk > 0:
                # === TP: cari swing low M5 di BAWAH entry sebagai target ===
                tp_candidates = []
                for idx in ms_m5["swing_lows"]:
                    sl_p = float(df["low"].iloc[idx])
                    if sl_p < entry_zone["low"]:
                        natural_rr = (entry_mid - sl_p) / risk
                        if natural_rr >= rr_set[0]:
                            tp_candidates.append((sl_p, natural_rr))
                tp_candidates.sort(key=lambda x: x[1])

                tp_zones = []
                for i, (rr_target, label) in enumerate(zip(rr_set, tp_labels)):
                    if i < len(tp_candidates):
                        sl_p, _ = tp_candidates[i]
                        tp_zones.append({**shrink(sl_p - zw / 2, sl_p + zw / 2), "rr": round((entry_mid - sl_p) / risk, 2), "label": label, "source": "M5 swing"})
                    else:
                        tp_zones.append({**shrink(entry_mid - risk * rr_target - zw / 2, entry_mid - risk * rr_target + zw / 2), "rr": rr_target, "label": label, "source": "RR ratio"})

    # Range & session checks
    adx = compute_adx(df_m15)
    session = get_session()
    in_news, news_event = is_news_window()

    # === TECHNICAL INDICATORS (M15 timeframe untuk konfirmasi) ===
    rsi_series = compute_rsi(df_m15["close"], 14)
    rsi_val = float(rsi_series.iloc[-1])
    rsi_div = detect_rsi_divergence(df_m15["close"], rsi_series, 50)
    rsi_sig = rsi_signal(rsi_val)

    macd_data = compute_macd(df_m15["close"])
    hist_now = float(macd_data["histogram"].iloc[-1])
    hist_prev = float(macd_data["histogram"].iloc[-2])
    macd_sig = macd_signal(hist_now, hist_prev)

    bb_data = compute_bollinger(df_m15["close"], 20, 2.0)
    bb_sig = bollinger_signal(price, bb_data)
    bb_squeeze = detect_bb_squeeze(bb_data, 0.05)

    stoch_data = compute_stoch_rsi(df_m15["close"])
    k_now = float(stoch_data["k"].iloc[-1])
    d_now = float(stoch_data["d"].iloc[-1])
    k_prev = float(stoch_data["k"].iloc[-2])
    d_prev = float(stoch_data["d"].iloc[-2])
    stoch_sig = stoch_rsi_signal(k_now, d_now, k_prev, d_prev)

    vwap_series = compute_vwap(df_m15)
    vwap_val = float(vwap_series.iloc[-1]) if not vwap_series.empty else price
    vwap_sig = vwap_signal(price, vwap_val)

    atr_series = compute_atr(df_m15)
    atr_val = float(atr_series.iloc[-1])
    atr_pct = atr_percent(price, atr_val)

    confluence = multi_indicator_confluence(
        rsi_val=rsi_val,
        rsi_div=rsi_div,
        macd_sig=macd_sig,
        stoch_sig=stoch_sig,
        bb_sig=bb_sig,
        vwap_sig=vwap_sig,
        adx=adx,
    )

    # Score
    score_info = score_setup(
        h4_trend=h4_trend,
        h1_trend=h1_trend,
        m15_struct=ms_m15,
        m5_struct=ms_m5,
        entry_type=entry_type,
        is_killzone=session["in_killzone"],
        adx=adx,
        in_news=in_news,
    )

    # Boost score jika multi-indicator confluence tinggi
    ind_score = confluence["score"]  # 0-6
    if ind_score >= 4 and signal in ("BUY", "SELL"):
        # Cek direction confluence
        if signal == "BUY" and confluence["bullish_count"] >= 4:
            score_info["score"] = min(10, score_info["score"] + 1)
            score_info["breakdown"].append(f"✓ Multi-indikator bullish ({confluence['bullish_count']}/6) (+1)")
        elif signal == "SELL" and confluence["bearish_count"] >= 4:
            score_info["score"] = min(10, score_info["score"] + 1)
            score_info["breakdown"].append(f"✓ Multi-indikator bearish ({confluence['bearish_count']}/6) (+1)")
    score_info["high_prob"] = score_info["score"] >= 7

    # Skip reasons
    skip_reasons = []
    if bias == "neutral":
        skip_reasons.append("HTF bias tidak jelas (neutral)")
    if h4_trend != h1_trend and h4_trend != "neutral" and h1_trend != "neutral":
        skip_reasons.append(f"H4 ({h4_trend}) vs H1 ({h1_trend}) kontras")
    if not session["in_killzone"]:
        skip_reasons.append("Di luar killzone (London/NY)")
    if adx < 20:
        skip_reasons.append(f"Market ranging (ADX {adx:.1f} < 20)")
    if in_news:
        skip_reasons.append(f"Ada news: {news_event}")
    if entry_zone is None:
        skip_reasons.append("Tidak ada OB/FVG valid di TF target")

    return {
        "symbol": td_sym, "timeframe": timeframe, "price": price, "mode": mode,
        "signal": signal, "bias": bias,
        "d1_trend": d1_trend, "h4_trend": h4_trend, "h1_trend": h1_trend,
        "m30_trend": m30_trend, "m15_trend": m15_trend, "m5_trend": m5_trend,
        "votes": votes,
        "h1_choch": ms_h1["choch"], "m15_choch": ms_m15["choch"], "m5_choch": ms_m5["choch"],
        "adx": adx, "session": session, "in_news": in_news, "news_event": news_event,
        "entry_zone": entry_zone, "entry_zone_full": entry_zone_full,
        "sl_zone": sl_zone, "tp_zones": tp_zones,
        "entry_type": entry_type, "m5_choch": m5_choch, "m5_bos": ms_m5.get("bos"),
        "score": score_info["score"], "score_breakdown": score_info["breakdown"],
        "high_prob": score_info["high_prob"],
        "skip_reasons": skip_reasons,
        # Technical indicators
        "tech": {
            "rsi": rsi_val,
            "rsi_signal": rsi_sig,
            "rsi_div": rsi_div,
            "macd": macd_sig,
            "macd_hist": hist_now,
            "bb": bb_sig,
            "bb_squeeze": bb_squeeze,
            "stoch_rsi": stoch_sig,
            "vwap": vwap_sig,
            "vwap_val": vwap_val,
            "atr": atr_val,
            "atr_pct": atr_pct,
            "confluence": confluence,
        },
    }


def format_analysis(result: dict) -> str:
    """Format hasil analisa jadi pesan Telegram - AI BEDAH CHART style."""
    p = result["price"]
    sig = result["signal"]
    score = result["score"]
    high_prob = result["high_prob"]

    # Signal emoji
    if sig == "BUY":
        sig_emoji = "🟢"
    elif sig == "SELL":
        sig_emoji = "🔴"
    else:
        sig_emoji = "🟡"

    fmtz = lambda z: f"{z['low']:.2f}–{z['high']:.2f}" if z else "-"

    # Header
    mode_emoji = {"scalping": "⚡", "intraday": "🎯", "swing": "🌊"}.get(result.get("mode", "intraday"), "🎯")
    mode_label = {"scalping": "SCALPING", "intraday": "INTRADAY", "swing": "SWING"}.get(result.get("mode", "intraday"), "INTRADAY")
    text = f"""📊 <b>AI BEDAH CHART — {result['symbol']} · {result['timeframe']}</b>
   {mode_emoji} Mode: <b>{mode_label}</b> · <i>analisa AI · alat bantu, BUKAN sinyal resmi</i>

"""

    # STRUKTUR (SMC)
    structure_last = "none"
    if result.get("h1_choch") or result.get("m15_choch"):
        choch = result.get("h1_choch") or result.get("m15_choch")
        structure_last = f"{choch.upper()} CHoCh @{p:.2f} (recent)"

    # Tentukan zona (discount/premium)
    if result["h4_trend"] == "bullish" or result["h1_trend"] == "bullish":
        zona = f"discount 73% (zona PREMIUM untuk buy)"
    elif result["h4_trend"] == "bearish" or result["h1_trend"] == "bearish":
        zona = f"premium 73% (zona DISCOUNT untuk sell)"
    else:
        zona = "netral 50%"

    # === 6-TIMEFRAME TREND MATRIX ===
    def tf_emoji(t):
        return {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(t, "⚪")

    d1_e = tf_emoji(result.get("d1_trend", "neutral"))
    h4_e = tf_emoji(result.get("h4_trend", "neutral"))
    h1_e = tf_emoji(result.get("h1_trend", "neutral"))
    m30_e = tf_emoji(result.get("m30_trend", "neutral"))
    m15_e = tf_emoji(result.get("m15_trend", "neutral"))
    m5_e = tf_emoji(result.get("m5_trend", "neutral"))

    votes = result.get("votes", {})
    vote_text = ""
    if votes:
        vote_text = f"\n• Voting: 🟢{votes.get('bullish', 0)} vs 🔴{votes.get('bearish', 0)} (HTF-weighted)"

    text += f"""🏛️ <b>STRUKTUR (SMC) — 6 TIMEFRAME</b>
• HTF : D1 {d1_e} · H4 {h4_e} · H1 {h1_e}
• MTF : M30 {m30_e} · M15 {m15_e}
• LTF : M5  {m5_e}{vote_text}
• Struktur terakhir: {structure_last}
• Harga <b>{p:.2f}</b> · zona {zona}
• Likuiditas: {'resting di BSL' if result['signal'] != 'BUY' else 'resting di SSL'}

"""

    # === TECHNICAL INDICATORS (M15) ===
    if "tech" in result:
        t = result["tech"]
        # Build RSI signal line
        rsi_emoji = "🟢" if t["rsi_signal"] in ("oversold", "bullish") else "🔴" if t["rsi_signal"] in ("overbought", "bearish") else "⚪"
        # MACD signal
        macd_emoji = "🟢" if "bullish" in t["macd"] else "🔴" if "bearish" in t["macd"] else "⚪"
        # Bollinger
        bb_emoji = "🟢" if t["bb"] == "oversold" else "🔴" if t["bb"] == "overbought" else "⚪"
        # Stoch RSI
        stoch_emoji = "🟢" if t["stoch_rsi"] in ("oversold", "bullish_cross") else "🔴" if t["stoch_rsi"] in ("overbought", "bearish_cross") else "⚪"
        # VWAP
        vwap_emoji = "🟢" if t["vwap"] == "above" else "🔴" if t["vwap"] == "below" else "⚪"
        # Confluence
        cf = t["confluence"]
        if cf["bullish_count"] > cf["bearish_count"]:
            conf_emoji = f"🟢 {cf['bullish_count']}/{cf['total']} bullish"
        elif cf["bearish_count"] > cf["bullish_count"]:
            conf_emoji = f"🔴 {cf['bearish_count']}/{cf['total']} bearish"
        else:
            conf_emoji = f"⚪ mixed {cf['bullish_count']}/{cf['bearish_count']}"

        div_text = ""
        if t["rsi_div"] != "none":
            div_text = f"\n• Divergence: <b>{t['rsi_div']}</b> (strong signal)"

        text += f"""📈 <b>TECHNICAL INDICATORS (M15)</b>
• RSI(14): {rsi_emoji} {t['rsi']:.1f} ({t['rsi_signal']}){div_text}
• MACD: {macd_emoji} {t['macd']} (hist: {t['macd_hist']:+.3f})
• Bollinger: {bb_emoji} {t['bb']}{' | SQUEEZE detected' if t['bb_squeeze'] else ''}
• Stoch RSI: {stoch_emoji} {t['stoch_rsi']}
• VWAP: {vwap_emoji} {t['vwap']} ({t['vwap_val']:.2f})
• ATR(14): {t['atr']:.2f} ({t['atr_pct']:.2f}% of price)
• Confluence: {conf_emoji}

"""

    # FUNDAMENTAL - real-time data
    try:
        text += format_fundamental_block(result.get("_api_key", ""), result["symbol"]) + "\n\n"
    except Exception as e:
        text += f"""📰 <b>FUNDAMENTAL</b>
• Data unavailable: {e}

"""

    # === IDEAL SETUP — AREA ZONA ENTRY/SL/TP (STRICT M5) ===
    if sig == "WAIT" or result["entry_zone"] is None:
        text += f"""🎯 <b>IDEAL SETUP</b>
🟡 {sig} — belum ada setup jelas
• Tunggu CHoCH valid di M5 (low TF)
• Avoid entry di area netral
• KonviksI: tunggu pullback ke OB atau break structure dulu

"""
    else:
        # === M5 KONFIRMASI STATUS ===
        m5c = result.get("m5_choch")
        m5b = result.get("m5_bos")
        confirm_text = ""
        if m5c:
            confirm_text = f"✅ M5 CHoCH {m5c.upper()} (entry trigger valid)"
        elif m5b:
            confirm_text = f"⚠️ M5 BOS {m5b.upper()} (tanpa CHoCH — weaker)"
        else:
            confirm_text = "❌ Belum ada M5 CHoCH/BOS (tunggu trigger)"

        # === AREA ZONA VISUAL ===
        entry_low = result["entry_zone"]["low"]
        entry_high = result["entry_zone"]["high"]
        sl_low = result["sl_zone"]["low"] if result["sl_zone"] else 0
        sl_high = result["sl_zone"]["high"] if result["sl_zone"] else 0
        emoji = "🟢" if sig == "BUY" else "🔴"
        e_type = result.get("entry_type", "none")
        e_label = {"OB": "Order Block", "FVG": "Fair Value Gap", "swing_low": "Swing Low", "swing_high": "Swing High"}.get(e_type, e_type)

        # Visual: area bar
        text += f"""🎯 <b>AREA ZONA (M5 — strict)</b>
{confirm_text}
• Tipe Entry : <b>{e_label}</b>
• Harga      : <b>{p:.2f}</b>
• Entry Zone : <b>{entry_low:.2f} — {entry_high:.2f}</b>  📍 ({e_type})
• Stop Loss  : <b>{sl_low:.2f} — {sl_high:.2f}</b>  🛑
"""
        # TP dengan source indicator
        for tp in result["tp_zones"]:
            source_icon = "🎯" if tp.get("source") == "M5 swing" else "📐"
            text += f"• {tp['label']:4}      : <b>{tp['low']:.2f} — {tp['high']:.2f}</b>  {source_icon} (RR +{tp['rr']}R)\n"

        # === RISK METER ===
        if result["sl_zone"] and result["entry_zone"]:
            entry_mid = (entry_low + entry_high) / 2
            sl_mid = (sl_low + sl_high) / 2
            risk_pips = abs(entry_mid - sl_mid)
            if p > 1000:
                risk_str = f"${risk_pips:.2f}"
            elif p > 50:
                risk_str = f"{risk_pips:.3f}"
            else:
                risk_str = f"{risk_pips * 10000:.1f} pips"
            text += f"• Risk         : <b>{risk_str}</b> per 1 lot\n"

        # KonviksI
        text += f"• KonviksI     : <b>{'TINGGI' if score >= 7 else 'SEDANG' if score >= 5 else 'KURANG'}</b> (skor {score}/10)\n\n"

    # ALASAN naratif panjang
    if sig == "SELL":
        if score >= 7:
            alasan = f"""🧠 <b>Alasan:</b> Gwl lihat setup SELL ini skenarionya menarik karena price udah di zona premium (73%) dan struktur bear solid — pullback ke OB {fmtz(result['entry_zone'])} punya probabilitas tinggi buat rejection. ADX {result['adx']:.1f} (trending {'kuat' if result['adx'] > 30 else 'moderat'}), dalam killzone, dan gak ada news high impact — confluence lengkap. Risk-reward 1:3 memungkinkan reward max di TP3. Setup SELL ini layak eksekusi kalau harga retest OB + ada rejection candle di M5."""
        else:
            alasan = f"""🧠 <b>Alasan:</b> Skenario SELL ada tapi confluence belum lengkap. Struktur H1 menunjukkan bias {result['h1_trend']}, tapi {('H4 vs H1 kontras' if result['h4_trend'] != result['h1_trend'] else 'M15 belum confirm')}. Entry pullback ke OB {fmtz(result['entry_zone'])} menarik tapi sebaiknya tunggu konfirmasi tambahan. Skor {score}/10 belum cukup untuk high-prob entry."""
    elif sig == "BUY":
        if score >= 7:
            alasan = f"""🧠 <b>Alasan:</b> Gwl lihat setup BUY ini skenarionya menarik karena price udah di zona discount (73%) dan struktur bull solid — pullback ke OB {fmtz(result['entry_zone'])} punya probabilitas tinggi buat bounce. ADX {result['adx']:.1f} (trending {'kuat' if result['adx'] > 30 else 'moderat'}), dalam killzone, dan gak ada news high impact — confluence lengkap. Risk-reward 1:3 memungkinkan reward max di TP3. Setup BUY ini layak eksekusi kalau harga retest OB + rejection candle bullish di M5."""
        else:
            alasan = f"""🧠 <b>Alasan:</b> Skenario BUY ada tapi confluence belum lengkap. Struktur H1 {result['h1_trend']}, tapi {('H4 vs H1 kontras' if result['h4_trend'] != result['h1_trend'] else 'M15 belum confirm')}. Entry pullback ke OB {fmtz(result['entry_zone'])} menarik tapi sebaiknya tunggu konfirmasi. Skor {score}/10 belum cukup."""
    else:
        alasan = f"""🧠 <b>Alasan:</b> Struktur {result['h4_trend']} di H4 dan {result['h1_trend']} di H1 belum memberikan bias jelas. ADX {result['adx']:.1f} {'trending' if result['adx'] > 20 else 'ranging'}. Tidak ada setup OB/FVG yang valid di TF target. Sebaiknya tunggu struktur terkonfirmasi dulu."""

    text += alasan + "\n\n"

    # INVALID KALAU
    if result["sl_zone"]:
        invalid_level = result["sl_zone"]["high"] if sig == "SELL" else result["sl_zone"]["low"]
        invalid = f"❌ <b>Invalid kalau:</b> close M5 di atas {invalid_level:.2f} (struktur rusak) · BOS {'bullish' if sig == 'SELL' else 'bearish'} baru terbentuk (trend reversal)\n\n"
    else:
        invalid = ""
    text += invalid

    # Bottom disclaimer
    text += """⚠️ <b>Ini analisa AI</b> — alat bantu, BUKAN sinyal resmi financial advice. Level harga real + struktur SMC, tapi arah pasar gak ada yang jamin. Konfirm + atur risiko sendiri."""

    return text


def quick_analyze(api_key: str, symbol: str, timeframe: str = "M5", mode: str = "intraday") -> str:
    """Shortcut untuk dipanggil bot. Mode: scalping/intraday/swing."""
    result = analyze_full(api_key, symbol, timeframe, mode)
    result["_api_key"] = api_key  # pass untuk format_fundamental_block
    return format_analysis(result)


def scan_pairs(api_key: str, pairs: list[str] = None) -> list[dict]:
    """Scan banyak pair SECARA PARALLEL, return list of setups high-probability."""
    if pairs is None:
        pairs = DEFAULT_SCAN_PAIRS
    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(analyze_full, api_key, pair, "M5"): pair for pair in pairs}
        for fut in as_completed(futures):
            pair = futures[fut]
            try:
                r = fut.result()
                if r["high_prob"]:
                    results.append(r)
            except Exception:
                continue
    # Sort by score desc
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results


def format_scan(results: list[dict]) -> str:
    """Format scan result jadi pesan."""
    if not results:
        return "❌ Tidak ada setup high-probability sekarang. Tunggu killzone berikutnya."

    text = f"🔥 <b>HIGH-PROB SCAN</b> — {len(results)} setup\n\n"
    for r in results:
        emoji = "🟢" if r["signal"] == "BUY" else "🔴"
        entry_text = ""
        if r["entry_zone"]:
            entry_text = f" Entry: {r['entry_zone']['low']:.2f}-{r['entry_zone']['high']:.2f}"
        text += f"{emoji} <b>{r['symbol']}</b> {r['signal']} (skor {r['score']}){entry_text}\n"
    return text

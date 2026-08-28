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
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timezone

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
    "EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCHF", "USDCAD",
    "EURJPY", "GBPJPY", "XAUUSD", "XAGUSD",
]

# === SESSION / KILLZONE (UTC) ===
KILLZONES = {
    "london": {"start": 1, "end": 4, "name": "London Killzone"},
    "newyork": {"start": 8, "end": 11, "name": "New York Killzone"},
    "london_ny": {"start": 13, "end": 16, "name": "London-NY Overlap"},
}

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


def fetch_candles(api_key: str, symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    """Fetch candle dari Twelve Data."""
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol, "interval": interval, "outputsize": limit,
        "order": "ASC", "apikey": api_key,
    }
    r = requests.get(url, params=params, timeout=20)
    data = r.json()
    if data.get("status") == "error":
        raise RuntimeError(data.get("message", "API error"))
    values = data.get("values")
    if not values:
        raise RuntimeError(f"No data for {symbol} {interval}")
    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"], format="%Y-%m-%d %H:%M:%S")
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


# === ICT/SMC FUNCTIONS ===

def get_market_structure(df: pd.DataFrame) -> dict:
    """Detect swing structure, trend, CHoCH, BOS."""
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    n = len(df)
    swing_highs, swing_lows = [], []
    for i in range(1, n - 1):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            swing_highs.append(i)
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swing_lows.append(i)

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
    """Detect Fair Value Gaps."""
    fvgs = []
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    n = len(df)
    for i in range(1, n - 1):
        if lows[i - 1] > highs[i - 2]:
            fvgs.append({"type": "bullish", "low": lows[i - 1], "high": highs[i - 2], "candle_idx": i - 2})
        if highs[i - 1] < lows[i - 2]:
            fvgs.append({"type": "bearish", "high": highs[i - 1], "low": lows[i - 2], "candle_idx": i - 2})
    return fvgs


def detect_order_blocks(df: pd.DataFrame) -> list[dict]:
    """Detect Order Blocks."""
    obses = []
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    opens = df["open"].tolist()
    closes = df["close"].tolist()
    n = len(df)
    for i in range(1, n - 1):
        if closes[i] < opens[i] and closes[i + 1] > opens[i + 1]:
            obses.append({"type": "bullish", "price": opens[i], "high": highs[i], "low": lows[i], "candle_idx": i})
        if closes[i] > opens[i] and closes[i + 1] < opens[i + 1]:
            obses.append({"type": "bearish", "price": opens[i], "high": highs[i], "low": lows[i], "candle_idx": i})
    return obses


def detect_liquidity(df: pd.DataFrame) -> dict:
    """Detect BSL/SSL levels."""
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    n = len(df)
    sl = [i for i in range(1, n - 1) if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]]
    sh = [i for i in range(1, n - 1) if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]]
    return {"ssl_price": min(lows) if sl else None, "bsl_price": max(highs) if sh else None,
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

def get_zone_width(price: float) -> float:
    """Adaptive zone width: 0.01% dari price, min 0.005 (untuk forex minor), max 0.5."""
    w = price * 0.0001
    return max(0.005, min(0.5, w))


def analyze_full(api_key: str, symbol: str, timeframe: str = "M5") -> dict:
    """High-probability analysis dengan multi-timeframe confluence.

    Returns dict dengan:
    - signal: BUY/SELL/WAIT
    - score: 0-10
    - high_prob: bool
    - entry_zone, sl_zone, tp_zones
    - bias_htf, structure_ltf
    - reasons
    - skip_reasons (kalau WAIT)
    """
    td_sym = SYMBOL_MAP.get(symbol.upper(), symbol)
    td_tf = TF_MAP.get(timeframe, "5min")

    # Fetch data
    df = fetch_candles(api_key, td_sym, td_tf, limit=200)
    df_h1 = fetch_candles(api_key, td_sym, "1h", limit=200)
    df_h4 = fetch_candles(api_key, td_sym, "4h", limit=100)
    df_m15 = fetch_candles(api_key, td_sym, "15min", limit=200)

    price = float(df["close"].iloc[-1])

    # Multi-TF structure
    ms_h4 = get_market_structure(df_h4)
    ms_h1 = get_market_structure(df_h1)
    ms_m15 = get_market_structure(df_m15)
    ms_m5 = get_market_structure(df)

    # Decide bias & signal
    h4_trend = ms_h4["trend"]
    h1_trend = ms_h1["trend"]
    bias = h1_trend if h1_trend != "neutral" else h4_trend

    if bias == "bullish":
        signal = "BUY"
    elif bias == "bearish":
        signal = "SELL"
    else:
        signal = "WAIT"

    # Detect entry zone di TF target
    fvgs = [f for f in detect_fvg(df) if not is_mitigated_fvg(f, df) and f["candle_idx"] >= len(df) - 30]
    obses = [o for o in detect_order_blocks(df) if not is_mitigated_ob(o, df) and o["candle_idx"] >= len(df) - 30]
    liq = detect_liquidity(df)

    entry_zone = None
    sl_zone = None
    tp_zones = []
    entry_type = "none"
    zw = get_zone_width(price)

    def shrink(low, high):
        mid = (low + high) / 2
        return {"low": mid - zw / 2, "high": mid + zw / 2}

    if signal == "BUY":
        bull_obs = [o for o in obses if o["type"] == "bullish" and o["high"] < price]
        bull_fvgs = [f for f in fvgs if f["type"] == "bullish" and f["high"] < price]
        if bull_obs:
            ob = bull_obs[-1]
            entry_zone = shrink(ob["low"], ob["high"])
            entry_type = "OB"
        elif bull_fvgs:
            fvg = bull_fvgs[-1]
            entry_zone = shrink(fvg["low"], fvg["high"])
            entry_type = "FVG"
        elif ms_m5["swing_lows"]:
            sl_price = float(df["low"].iloc[ms_m5["swing_lows"][-1]])
            entry_zone = shrink(sl_price - 0.25, sl_price + 0.25)
            entry_type = "swing_low"
    elif signal == "SELL":
        bear_obs = [o for o in obses if o["type"] == "bearish" and o["low"] > price]
        bear_fvgs = [f for f in fvgs if f["type"] == "bearish" and f["low"] > price]
        if bear_obs:
            ob = bear_obs[-1]
            entry_zone = shrink(ob["low"], ob["high"])
            entry_type = "OB"
        elif bear_fvgs:
            fvg = bear_fvgs[-1]
            entry_zone = shrink(fvg["low"], fvg["high"])
            entry_type = "FVG"
        elif ms_m5["swing_highs"]:
            sh_price = float(df["high"].iloc[ms_m5["swing_highs"][-1]])
            entry_zone = shrink(sh_price - 0.25, sh_price + 0.25)
            entry_type = "swing_high"

    # SL & TP - pakai swing yang dekat dengan price (max 2% dari price)
    if entry_zone and signal != "WAIT":
        entry_mid = (entry_zone["low"] + entry_zone["high"]) / 2
        max_sl_dist = abs(price) * 0.02  # max 2% dari price

        if signal == "BUY":
            # Cari swing low terdekat dengan price (di bawah entry)
            sl_candidates = []
            for idx in ms_m5["swing_lows"]:
                sw_low = float(df["low"].iloc[idx])
                if sw_low < entry_zone["low"] and (entry_zone["low"] - sw_low) <= max_sl_dist:
                    sl_candidates.append(sw_low)
            if liq["ssl_price"] and liq["ssl_price"] < entry_zone["low"] and (entry_zone["low"] - liq["ssl_price"]) <= max_sl_dist:
                sl_candidates.append(liq["ssl_price"])
            sl_ref = min(sl_candidates) if sl_candidates else (entry_zone["low"] - abs(price) * 0.005)

            sl_mid = sl_ref - abs(price) * 0.0005  # 5 pips buffer untuk XAU, scaled
            sl_zone = {"low": sl_mid - zw / 2, "high": sl_mid + zw / 2}
            risk = entry_mid - sl_zone["high"]
            if risk > 0:
                tp_zones = [
                    {**shrink(entry_mid + risk * 1 - zw / 2, entry_mid + risk * 1 + zw / 2), "rr": 1.0, "label": "TP1"},
                    {**shrink(entry_mid + risk * 1.5 - zw / 2, entry_mid + risk * 1.5 + zw / 2), "rr": 1.5, "label": "TP2"},
                    {**shrink(entry_mid + risk * 3 - zw / 2, entry_mid + risk * 3 + zw / 2), "rr": 3.0, "label": "TP3"},
                ]
        else:  # SELL
            # Cari swing high terdekat dengan price (di atas entry)
            sl_candidates = []
            for idx in ms_m5["swing_highs"]:
                sw_high = float(df["high"].iloc[idx])
                if sw_high > entry_zone["high"] and (sw_high - entry_zone["high"]) <= max_sl_dist:
                    sl_candidates.append(sw_high)
            if liq["bsl_price"] and liq["bsl_price"] > entry_zone["high"] and (liq["bsl_price"] - entry_zone["high"]) <= max_sl_dist:
                sl_candidates.append(liq["bsl_price"])
            sl_ref = max(sl_candidates) if sl_candidates else (entry_zone["high"] + abs(price) * 0.005)

            sl_mid = sl_ref + abs(price) * 0.0005
            sl_zone = {"low": sl_mid - zw / 2, "high": sl_mid + zw / 2}
            risk = sl_zone["low"] - entry_mid
            if risk > 0:
                tp_zones = [
                    {**shrink(entry_mid - risk * 1 - zw / 2, entry_mid - risk * 1 + zw / 2), "rr": 1.0, "label": "TP1"},
                    {**shrink(entry_mid - risk * 1.5 - zw / 2, entry_mid - risk * 1.5 + zw / 2), "rr": 1.5, "label": "TP2"},
                    {**shrink(entry_mid - risk * 3 - zw / 2, entry_mid - risk * 3 + zw / 2), "rr": 3.0, "label": "TP3"},
                ]

    # Range & session checks
    adx = compute_adx(df_m15)
    session = get_session()
    in_news, news_event = is_news_window()

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
        "symbol": td_sym, "timeframe": timeframe, "price": price,
        "signal": signal, "bias": bias,
        "h4_trend": h4_trend, "h1_trend": h1_trend, "m15_trend": ms_m15["trend"], "m5_trend": ms_m5["trend"],
        "h1_choch": ms_h1["choch"], "m15_choch": ms_m15["choch"],
        "adx": adx, "session": session, "in_news": in_news, "news_event": news_event,
        "entry_zone": entry_zone, "sl_zone": sl_zone, "tp_zones": tp_zones,
        "entry_type": entry_type,
        "score": score_info["score"], "score_breakdown": score_info["breakdown"],
        "high_prob": score_info["high_prob"],
        "skip_reasons": skip_reasons,
    }


def format_analysis(result: dict) -> str:
    """Format hasil analisa jadi pesan Telegram."""
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

    high_prob_badge = "🔥 HIGH PROB" if high_prob else "⚠️ SKIP"

    fmtz = lambda z: f"{z['low']:.2f}–{z['high']:.2f}" if z else "-"

    text = f"""📊 <b>{result['symbol']} · {result['timeframe']}</b>  {high_prob_badge}

💰 Harga: <b>{p:.2f}</b>
🎯 Sinyal: {sig_emoji} <b>{sig}</b>  (skor {score}/10)

━━━ MULTI-TIMEFRAME ━━━
• H4 Trend: {result['h4_trend'].upper()}
• H1 Trend: {result['h1_trend'].upper()}
• H1 CHoCH: {result['h1_choch'] or '-'}
• M15 Trend: {result['m15_trend'].upper()}
• M15 CHoCH: {result['m15_choch'] or '-'}

━━━ FILTERS ━━━
• ADX: {result['adx']:.1f} {'(trending)' if result['adx'] > 20 else '(ranging)'}
• Session: {result['session']['kz_name'] or 'off-hours'}
• News: {result['news_event'] or 'clear'}

━━━ IDEAL SETUP ━━━
"""
    if result["entry_zone"]:
        text += f"• Entry ({result['entry_type']}): {fmtz(result['entry_zone'])}\n"
        text += f"• SL: {fmtz(result['sl_zone'])}\n"
        for tp in result["tp_zones"]:
            text += f"• {tp['label']} (+{tp['rr']}R): {tp['low']:.2f}\n"
    else:
        text += "• Belum ada setup valid di TF target\n"

    text += "\n━━━ CONFLUENCE BREAKDOWN ━━━\n"
    for b in result["score_breakdown"]:
        text += f"• {b}\n"

    if result["skip_reasons"]:
        text += "\n━━━ SKIP REASONS ━━━\n"
        for r in result["skip_reasons"]:
            text += f"• {r}\n"

    if not high_prob:
        text += "\n❌ <b>SKIP — Skor di bawah 7, tidak high probability.</b>"
    else:
        text += "\n✅ <b>Entry layak (skor ≥ 7). Tunggu konfirmasi candle M5.</b>"

    text += "\n\n⚠️ Ini analisa AI · alat bantu, BUKAN sinyal resmi. Risk management sendiri."
    return text


def quick_analyze(api_key: str, symbol: str, timeframe: str = "M5") -> str:
    """Shortcut untuk dipanggil bot."""
    result = analyze_full(api_key, symbol, timeframe)
    return format_analysis(result)


# === MULTI-PAIR SCANNER ===

def scan_pairs(api_key: str, pairs: list[str] = None) -> list[dict]:
    """Scan banyak pair, return list of setups high-probability."""
    if pairs is None:
        pairs = DEFAULT_SCAN_PAIRS
    results = []
    for pair in pairs:
        try:
            r = analyze_full(api_key, pair, "M5")
            if r["high_prob"]:
                results.append(r)
        except Exception:
            continue
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

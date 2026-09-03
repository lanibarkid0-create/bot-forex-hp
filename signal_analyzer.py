"""Signal Analyzer — generate JSON trading signal.

Kerangka:
- Technical (SMC/ICT): 50% — BOS/CHoCH, OB/FVG, liquidity, killzone
- Fundamental: 30% — DXY, US10Y, VIX, news
- Order Flow: 20% — volume, wick ratio, absorption

Confidence = confluence-based (0-100), bukan subjektif.
"""

import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from analysis import (
    fetch_candles, get_market_structure, detect_fvg, detect_order_blocks,
    detect_liquidity, compute_rsi, compute_macd, compute_atr,
    SYMBOL_MAP, TF_MAP, is_news_window, get_session,
)
from fundamental import (
    get_dxy, get_us10y_yield, get_vix, get_finnhub_news,
    is_high_impact_news_soon, fetch_forexfactory_calendar,
)


# === KILLZONE SESSION (UTC) ===
def get_session_label() -> str:
    """Return current session/killzone label."""
    now = datetime.now(timezone.utc)
    h = now.hour
    if 1 <= h < 4:
        return "London Open"
    elif 8 <= h < 11:
        return "New York Open"
    elif 13 <= h < 16:
        return "Overlap"
    elif 0 <= h < 1 or 4 <= h < 8:
        return "Asia"
    else:
        return "Di luar killzone"


# === ENTRY MODEL DETECTION ===
def detect_entry_model(candle_idx: int, df) -> tuple[str, float]:
    """Tentukan entry type (Wick/Body/50% Body-to-Body) + level presisi.

    Returns: (entry_type, entry_level)
    """
    if candle_idx >= len(df) or candle_idx < 0:
        return "Body", 0.0
    row = df.iloc[candle_idx]
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    body_low, body_high = (o, c) if c > o else (c, o)
    body_50 = (body_low + body_high) / 2

    # Wick vs body ratio
    upper_wick = h - body_high
    lower_wick = body_low - l
    body_size = abs(c - o)

    # Kalau ada lower wick panjang (bullish OB) → entry diwick
    if lower_wick > body_size * 1.5:
        return "Wick", l + (lower_wick * 0.3)
    # Kalau ada upper wick panjang (bearish OB) → entry diwick
    if upper_wick > body_size * 1.5:
        return "Wick", h - (upper_wick * 0.3)
    # Default: 50% body-to-body (ICT standard)
    return "50% Body-to-Body", body_50


def compute_orderflow_proxy(df) -> dict:
    """Proxy order flow dari volume + wick ratio (free API tidak ada true delta).

    Returns: {volume_trend, absorption_detected, last_candle_strength, vol_ratio, wick_ratio}
    """
    if "volume" not in df.columns or len(df) < 20:
        return {
            "volume_trend": "unavailable",
            "absorption": False,
            "strength": "unknown",
            "vol_ratio": 0,
            "wick_ratio": 0,
            "last_candle_strength": "unknown",
        }

    vol = df["volume"].values.astype(float)
    last_vol = float(vol[-1])
    avg_vol_20 = float(vol[-20:].mean())
    vol_ratio = last_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

    # Wick analysis (absorption)
    last_row = df.iloc[-1]
    o, h, l, c = float(last_row["open"]), float(last_row["high"]), float(last_row["low"]), float(last_row["close"])
    body_size = abs(c - o)
    upper_wick = h - max(c, o)
    lower_wick = min(c, o) - l

    absorption = False
    wick_ratio = 0
    if body_size > 0:
        if lower_wick > body_size * 2:
            absorption = True
            wick_ratio = lower_wick / body_size
        elif upper_wick > body_size * 2:
            absorption = True
            wick_ratio = upper_wick / body_size

    return {
        "volume_trend": "high" if vol_ratio > 1.5 else "low" if vol_ratio < 0.5 else "normal",
        "vol_ratio": round(vol_ratio, 2),
        "absorption": absorption,
        "wick_ratio": round(wick_ratio, 2),
        "last_candle_strength": "strong" if vol_ratio > 1.2 else "weak" if vol_ratio < 0.8 else "medium",
    }


def find_swing_levels(df, lookback: int = 50) -> dict:
    """Cari swing high/low terakhir untuk TP/Invalidation."""
    if len(df) < lookback:
        lookback = len(df)
    recent = df.tail(lookback)
    return {
        "recent_high": float(recent["high"].max()),
        "recent_low": float(recent["low"].min()),
        "last_swing_high_idx": recent["high"].idxmax(),
        "last_swing_low_idx": recent["low"].idxmin(),
    }


def generate_signal(api_key: str, finnhub_key: str, symbol: str, timeframe: str = "M3") -> dict:
    """Generate JSON trading signal.

    Args:
        api_key: TwelveData API key
        finnhub_key: Finnhub API key (optional, "" kalau tidak ada)
        symbol: trading pair (XAUUSD, EURUSD, etc)
        timeframe: M1, M3, M5, M15

    Returns:
        dict JSON sesuai format di prompt
    """
    td_sym = SYMBOL_MAP.get(symbol.upper(), symbol)
    # M3 → fallback ke M5 (TwelveData tidak support 3min)
    if timeframe.upper() == "M3":
        td_tf = "5min"
    else:
        td_tf = TF_MAP.get(timeframe, "5min")

    # === PRE-CHECK: news risk ===
    news_soon, news_desc = is_high_impact_news_soon(finnhub_key or "", minutes=30)
    if news_soon:
        return {
            "pair": symbol.upper(),
            "timeframe": timeframe,
            "signal": "NO_TRADE",
            "confidence": 0,
            "session": get_session_label(),
            "entry_price": 0.0,
            "entry_type": "N/A",
            "stop_loss": 0.0,
            "take_profit_1": 0.0,
            "take_profit_2": 0.0,
            "risk_reward_tp1": 0.0,
            "technical_summary": "Setup dicekal karena ada rilis high-impact.",
            "fundamental_summary": news_desc,
            "orderflow_summary": "Tidak relevan - news risk dominan.",
            "invalidation": "Tunggu setelah news release (±30 menit).",
            "news_risk": news_desc,
        }

    # === FETCH DATA (parallel) ===
    # HTF: H1 (bias) | Entry TF: tf | Confirmation: M15
    h1_limit = 200
    tf_limit = 200
    m15_limit = 100

    fetched = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            ex.submit(fetch_candles, api_key, td_sym, "1h", h1_limit): "h1",
            ex.submit(fetch_candles, api_key, td_sym, td_tf, tf_limit): "tf",
            ex.submit(fetch_candles, api_key, td_sym, "15min", m15_limit): "m15",
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                fetched[key] = fut.result()
            except Exception:
                fetched[key] = None

    df_h1 = fetched.get("h1")
    df_tf = fetched.get("tf")
    df_m15 = fetched.get("m15")

    if df_h1 is None or df_tf is None or df_m15 is None:
        return {
            "pair": symbol.upper(),
            "timeframe": timeframe,
            "signal": "NO_TRADE",
            "confidence": 0,
            "session": get_session_label(),
            "entry_price": 0.0,
            "entry_type": "N/A",
            "stop_loss": 0.0,
            "take_profit_1": 0.0,
            "take_profit_2": 0.0,
            "risk_reward_tp1": 0.0,
            "technical_summary": "Gagal fetch data market.",
            "fundamental_summary": "Data unavailable.",
            "orderflow_summary": "Data unavailable.",
            "invalidation": "Cek koneksi atau API key.",
            "news_risk": "unknown",
        }

    # === TECHNICAL ANALYSIS (SMC/ICT) ===
    price = float(df_tf["close"].iloc[-1])

    # HTF bias (H1)
    ms_h1 = get_market_structure(df_h1)
    htf_bias = ms_h1["trend"]  # bullish/bearish/neutral

    # Entry TF structure
    ms_tf = get_market_structure(df_tf)
    tf_choch = ms_tf["choch"]
    tf_bos = ms_tf["bos"]
    tf_trend = ms_tf["trend"]

    # FVG & OB di TF entry
    fvgs = detect_fvg(df_tf)
    obses = detect_order_blocks(df_tf)
    liq = detect_liquidity(df_tf)

    # Pilih OB searah HTF bias
    bias_signal = htf_bias if htf_bias != "neutral" else tf_trend
    if bias_signal == "bullish":
        bull_obs = [o for o in obses if o["type"] == "bullish" and o["high"] < price]
        valid_obs = bull_obs
        valid_fvgs = [f for f in fvgs if f["type"] == "bullish" and f["high"] < price]
        entry_dir = "BUY"
    elif bias_signal == "bearish":
        bear_obs = [o for o in obses if o["type"] == "bearish" and o["low"] > price]
        valid_obs = bear_obs
        valid_fvgs = [f for f in fvgs if f["type"] == "bearish" and f["low"] > price]
        entry_dir = "SELL"
    else:
        return {
            "pair": symbol.upper(),
            "timeframe": timeframe,
            "signal": "NO_TRADE",
            "confidence": 0,
            "session": get_session_label(),
            "entry_price": 0.0,
            "entry_type": "N/A",
            "stop_loss": 0.0,
            "take_profit_1": 0.0,
            "take_profit_2": 0.0,
            "risk_reward_tp1": 0.0,
            "technical_summary": f"Struktur netral - H1: {htf_bias}, TF: {tf_trend}. Tunggu CHoCH.",
            "fundamental_summary": "N/A",
            "orderflow_summary": "N/A",
            "invalidation": "Setup muncul saat ada CHoCH atau BOS searah.",
            "news_risk": "clear" if not news_soon else news_desc,
        }

    # Pilih entry zone (OB > FVG > swing)
    entry_zone = None
    entry_type = "Body"
    if valid_obs:
        ob = valid_obs[-1]
        entry_zone = {"low": ob["low"], "high": ob["high"], "candle_idx": ob["candle_idx"]}
        entry_type = "Body"  # OB = body candle
    elif valid_fvgs:
        fvg = valid_fvgs[-1]
        entry_zone = {"low": fvg["low"], "high": fvg["high"], "candle_idx": fvg["candle_idx"]}
        entry_type = "50% Body-to-Body"  # FVG entry di 50%
    else:
        return {
            "pair": symbol.upper(),
            "timeframe": timeframe,
            "signal": "NO_TRADE",
            "confidence": 0,
            "session": get_session_label(),
            "entry_price": 0.0,
            "entry_type": "N/A",
            "stop_loss": 0.0,
            "take_profit_1": 0.0,
            "take_profit_2": 0.0,
            "risk_reward_tp1": 0.0,
            "technical_summary": f"Setup {entry_dir} tapi tidak ada OB/FVG valid di TF entry.",
            "fundamental_summary": "N/A",
            "orderflow_summary": "N/A",
            "invalidation": "Tunggu terbentuk OB/FVG baru.",
            "news_risk": "clear",
        }

    # Entry price presisi (Wick/Body/50%)
    entry_type_detailed, entry_price = detect_entry_model(
        entry_zone["candle_idx"], df_tf
    )
    # Override ke entry_type_detailed
    if entry_type_detailed:
        entry_type = entry_type_detailed

    # SL & TP
    atr_series = compute_atr(df_tf)
    atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else price * 0.001
    swings = find_swing_levels(df_tf, lookback=50)

    if entry_dir == "BUY":
        # SL di bawah liquidity sweep / swing low
        sl_price = min(
            swings["recent_low"] - atr_val * 0.5,
            liq.get("ssl_price", swings["recent_low"]) - atr_val * 0.3,
        )
        # TP1: nearest resistance (FVG high / swing high)
        tp1 = price + (entry_price - sl_price) * 1.5  # RR 1:1.5
        tp2 = swings["recent_high"] + atr_val * 0.3
    else:  # SELL
        sl_price = max(
            swings["recent_high"] + atr_val * 0.5,
            liq.get("bsl_price", swings["recent_high"]) + atr_val * 0.3,
        )
        tp1 = price - (sl_price - entry_price) * 1.5
        tp2 = swings["recent_low"] - atr_val * 0.3

    risk = abs(entry_price - sl_price)
    reward_tp1 = abs(tp1 - entry_price)
    rr_tp1 = reward_tp1 / risk if risk > 0 else 0

    # Technical summary
    tech_summary = (
        f"Bias H1: {htf_bias}, TF: {tf_trend}. "
        f"CHoCH: {tf_choch or 'none'}, BOS: {tf_bos or 'none'}. "
        f"Entry di {'OB' if valid_obs else 'FVG'} {entry_zone['low']:.2f}-{entry_zone['high']:.2f}."
    )

    # === FUNDAMENTAL (parallel fetch) ===
    fund_data = {}
    if finnhub_key:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {
                ex.submit(get_dxy, finnhub_key): "dxy",
                ex.submit(get_us10y_yield, finnhub_key): "us10y",
                ex.submit(get_vix, finnhub_key): "vix",
                ex.submit(get_finnhub_news, finnhub_key, "forex"): "news",
            }
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    fund_data[key] = fut.result()
                except Exception:
                    fund_data[key] = None

    dxy = fund_data.get("dxy", {})
    us10y = fund_data.get("us10y", {})
    vix = fund_data.get("vix", {})
    news = fund_data.get("news", [])

    # DXY correlation
    dxy_bullish_xau = (dxy.get("change_pct", 0) < 0)  # DXY turun = XAU naik
    fund_summary = []
    if dxy:
        dxy_dir = "naik" if dxy["change_pct"] > 0 else "turun"
        corr_ok = (entry_dir == "BUY" and dxy_bullish_xau) or (entry_dir == "SELL" and not dxy_bullish_xau)
        fund_summary.append(f"DXY {dxy_dir} ({dxy['change_pct']:+.2f}%)")
    if us10y:
        yld_dir = "naik" if us10y["change_pct"] > 0 else "turun"
        fund_summary.append(f"US10Y {yld_dir} ({us10y['change_pct']:+.2f}%)")
    if vix:
        fund_summary.append(f"VIX {vix['current']} ({vix['level']})")
    if not fund_summary:
        fund_summary = ["Data fundamental unavailable (Finnhub key tidak di-set)"]

    fund_text = ". ".join(fund_summary) + "."

    # === ORDER FLOW ===
    oflow = compute_orderflow_proxy(df_tf)
    vol_ratio = oflow.get("vol_ratio", 0)
    oflow_text = (
        f"Volume {vol_ratio}x avg, "
        f"{'absorption detected' if oflow.get('absorption') else 'no absorption'}"
    )

    # === CONFLUENCE SCORING ===
    score = 0
    breakdown = {}

    # Technical (max 50)
    tech_score = 0
    if htf_bias == entry_dir.lower():  # HTF searah
        tech_score += 15
    if tf_choch == entry_dir.lower():
        tech_score += 10
    if tf_bos == entry_dir.lower():
        tech_score += 5
    if valid_obs:  # ada OB valid
        tech_score += 10
    elif valid_fvgs:  # ada FVG valid
        tech_score += 5
    if liq.get("ssl_price" if entry_dir == "BUY" else "bsl_price"):
        tech_score += 5  # liquidity target tersedia
    if get_session_label() in ("London Open", "New York Open", "Overlap"):
        tech_score += 5  # dalam killzone
    breakdown["technical"] = min(50, tech_score)

    # Fundamental (max 30)
    fund_score = 0
    if dxy:
        if (entry_dir == "BUY" and dxy.get("change_pct", 0) < -0.1) or \
           (entry_dir == "SELL" and dxy.get("change_pct", 0) > 0.1):
            fund_score += 15  # DXY searah
        else:
            fund_score += 5  # DXY netral
    if us10y:
        if (entry_dir == "BUY" and us10y.get("change_pct", 0) < 0) or \
           (entry_dir == "SELL" and us10y.get("change_pct", 0) > 0):
            fund_score += 10
        else:
            fund_score += 3
    if vix:
        # VIX tinggi = risk-off = XAU bullish
        if entry_dir == "BUY" and vix.get("level") in ("elevated", "extreme"):
            fund_score += 5
        elif entry_dir == "SELL" and vix.get("level") == "low":
            fund_score += 5
    breakdown["fundamental"] = min(30, fund_score)

    # Order Flow (max 20)
    oflow_score = 0
    if oflow.get("absorption"):
        oflow_score += 10
    if oflow.get("vol_ratio", 0) > 1.2:
        oflow_score += 5
    if oflow.get("last_candle_strength") == "strong":
        oflow_score += 5
    breakdown["orderflow"] = min(20, oflow_score)

    confidence = breakdown["technical"] + breakdown["fundamental"] + breakdown["orderflow"]

    # NO_TRADE kalau confidence rendah
    if confidence < 30:
        entry_dir = "NO_TRADE"

    # Invalidation
    if entry_dir == "BUY":
        invalidation = f"Close {timeframe} di bawah {sl_price:.2f} (struktur SL)."
    elif entry_dir == "SELL":
        invalidation = f"Close {timeframe} di atas {sl_price:.2f} (struktur SL)."
    else:
        invalidation = "Tunggu setup valid (CHoCH + OB + killzone)."

    return {
        "pair": symbol.upper(),
        "timeframe": timeframe,
        "signal": entry_dir,
        "confidence": confidence,
        "session": get_session_label(),
        "entry_price": round(entry_price, 5) if entry_dir != "NO_TRADE" else 0.0,
        "entry_type": entry_type if entry_dir != "NO_TRADE" else "N/A",
        "stop_loss": round(sl_price, 5) if entry_dir != "NO_TRADE" else 0.0,
        "take_profit_1": round(tp1, 5) if entry_dir != "NO_TRADE" else 0.0,
        "take_profit_2": round(tp2, 5) if entry_dir != "NO_TRADE" else 0.0,
        "risk_reward_tp1": round(rr_tp1, 2) if entry_dir != "NO_TRADE" else 0.0,
        "technical_summary": tech_summary,
        "fundamental_summary": fund_text,
        "orderflow_summary": oflow_text,
        "invalidation": invalidation,
        "news_risk": news_desc if news_soon else "clear (no high-impact dalam 30 menit)",
    }


def format_signal_json(signal: dict) -> str:
    """Format signal dict jadi JSON string (compact, no markdown)."""
    return json.dumps(signal, indent=2, ensure_ascii=False)

"""Advanced technical indicators untuk high-probability trading signals.

Includes:
- RSI (Relative Strength Index) + divergence
- MACD (Moving Average Convergence Divergence) + divergence
- Bollinger Bands (squeeze, breakout)
- Stochastic RSI
- VWAP (Volume Weighted Average Price)
- ATR (Average True Range) - untuk dynamic SL/TP
- ADX (Average Directional Index) - trend strength
"""

import numpy as np
import pandas as pd


# === RSI ===

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI standard."""
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def detect_rsi_divergence(closes: pd.Series, rsi: pd.Series, lookback: int = 30) -> str:
    """Detect RSI divergence:
    - Regular bullish: price makes lower low, RSI makes higher low → BUY
    - Regular bearish: price makes higher high, RSI makes lower high → SELL
    - Hidden bullish: price makes higher low, RSI makes lower low → BUY
    - Hidden bearish: price makes lower high, RSI makes higher high → SELL
    """
    if len(closes) < lookback:
        return "none"

    recent_close = closes.iloc[-lookback:]
    recent_rsi = rsi.iloc[-lookback:]

    # Find 2 last swing lows (for bullish) and 2 last swing highs (for bearish)
    price_lows = []
    rsi_lows = []
    for i in range(2, len(recent_close) - 2):
        if (recent_close.iloc[i] < recent_close.iloc[i-1] and
            recent_close.iloc[i] < recent_close.iloc[i+1] and
            recent_close.iloc[i] < recent_close.iloc[i-2] and
            recent_close.iloc[i] < recent_close.iloc[i+2]):
            price_lows.append((i, recent_close.iloc[i]))
            rsi_lows.append((i, recent_rsi.iloc[i]))

    price_highs = []
    rsi_highs = []
    for i in range(2, len(recent_close) - 2):
        if (recent_close.iloc[i] > recent_close.iloc[i-1] and
            recent_close.iloc[i] > recent_close.iloc[i+1] and
            recent_close.iloc[i] > recent_close.iloc[i-2] and
            recent_close.iloc[i] > recent_close.iloc[i+2]):
            price_highs.append((i, recent_close.iloc[i]))
            rsi_highs.append((i, recent_rsi.iloc[i]))

    # Check bullish divergence (2 swing lows)
    if len(price_lows) >= 2:
        p1, p2 = price_lows[-2][1], price_lows[-1][1]
        r1, r2 = rsi_lows[-2][1], rsi_lows[-1][1]
        if p2 < p1 and r2 > r1:  # price lower low, RSI higher low
            return "regular_bullish"
        if p2 > p1 and r2 < r1:  # price higher low, RSI lower low
            return "hidden_bullish"

    # Check bearish divergence (2 swing highs)
    if len(price_highs) >= 2:
        p1, p2 = price_highs[-2][1], price_highs[-1][1]
        r1, r2 = rsi_highs[-2][1], rsi_highs[-1][1]
        if p2 > p1 and r2 < r1:  # price higher high, RSI lower high
            return "regular_bearish"
        if p2 < p1 and r2 > r1:  # price lower high, RSI higher high
            return "hidden_bearish"

    return "none"


def rsi_signal(rsi_value: float) -> str:
    """Interpretasi RSI value."""
    if rsi_value >= 70:
        return "overbought"
    elif rsi_value <= 30:
        return "oversold"
    elif rsi_value >= 55:
        return "bullish"
    elif rsi_value <= 45:
        return "bearish"
    else:
        return "neutral"


# === MACD ===

def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD line, signal, histogram."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def macd_signal(histogram_now: float, histogram_prev: float) -> str:
    """MACD signal based on histogram."""
    if histogram_now > 0 and histogram_prev <= 0:
        return "bullish_cross"
    elif histogram_now < 0 and histogram_prev >= 0:
        return "bearish_cross"
    elif histogram_now > 0:
        return "bullish"
    elif histogram_now < 0:
        return "bearish"
    else:
        return "neutral"


# === Bollinger Bands ===

def compute_bollinger(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict:
    """Bollinger Bands."""
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    return {
        "upper": sma + (std * std_dev),
        "middle": sma,
        "lower": sma - (std * std_dev),
    }


def bollinger_signal(price: float, bb: dict) -> str:
    """Sinyal BB berdasarkan posisi harga."""
    if pd.isna(bb["upper"].iloc[-1]) or pd.isna(bb["lower"].iloc[-1]):
        return "neutral"
    upper = bb["upper"].iloc[-1]
    lower = bb["lower"].iloc[-1]
    middle = bb["middle"].iloc[-1]
    if price >= upper:
        return "overbought"
    elif price <= lower:
        return "oversold"
    elif price > middle:
        return "upper_half"
    else:
        return "lower_half"


def detect_bb_squeeze(bb: dict, threshold: float = 0.05) -> bool:
    """Detect Bollinger Band squeeze (low volatility → potential breakout)."""
    if len(bb["upper"]) < 20 or pd.isna(bb["upper"].iloc[-1]):
        return False
    upper = bb["upper"].iloc[-1]
    lower = bb["lower"].iloc[-1]
    middle = bb["middle"].iloc[-1]
    if pd.isna(middle) or middle == 0:
        return False
    width = (upper - lower) / middle
    return width < threshold


# === Stochastic RSI ===

def compute_stoch_rsi(series: pd.Series, rsi_period: int = 14, stoch_period: int = 14, k_smooth: int = 3, d_smooth: int = 3) -> dict:
    """Stochastic RSI."""
    rsi = compute_rsi(series, rsi_period)
    rsi_min = rsi.rolling(stoch_period).min()
    rsi_max = rsi.rolling(stoch_period).max()
    stoch = ((rsi - rsi_min) / (rsi_max - rsi_min).replace(0, 1e-10)) * 100
    k = stoch.rolling(k_smooth).mean()
    d = k.rolling(d_smooth).mean()
    return {"k": k, "d": d}


def stoch_rsi_signal(k_now: float, d_now: float, k_prev: float, d_prev: float) -> str:
    """Stochastic RSI signal."""
    if pd.isna(k_now) or pd.isna(d_now):
        return "neutral"
    if k_now > 80 and d_now > 80:
        return "overbought"
    if k_now < 20 and d_now < 20:
        return "oversold"
    if k_now > d_now and k_prev <= d_prev:
        return "bullish_cross"
    if k_now < d_now and k_prev >= d_prev:
        return "bearish_cross"
    return "neutral"


# === VWAP ===

def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """Volume Weighted Average Price (intraday)."""
    if "volume" not in df.columns or df["volume"].sum() == 0:
        # No volume, fallback to typical price SMA
        typical = (df["high"] + df["low"] + df["close"]) / 3
        return typical.rolling(20).mean()

    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum()
    cum_vp = (typical * df["volume"]).cumsum()
    return cum_vp / cum_vol.replace(0, 1e-10)


def vwap_signal(price: float, vwap_value: float) -> str:
    """VWAP signal."""
    if pd.isna(vwap_value) or vwap_value == 0:
        return "neutral"
    if price > vwap_value * 1.001:  # 0.1% above
        return "above"
    elif price < vwap_value * 0.999:  # 0.1% below
        return "below"
    return "at"


# === ATR ===

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def atr_percent(price: float, atr_value: float) -> float:
    """ATR as % of price."""
    if price == 0:
        return 0
    return (atr_value / price) * 100


# === ADX ===

def compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Average Directional Index."""
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

    atr = pd.Series(tr).rolling(period).mean().values
    plus_di = 100 * pd.Series(plus_dm).rolling(period).mean().values / np.where(atr == 0, 1, atr)
    minus_di = 100 * pd.Series(minus_dm).rolling(period).mean().values / np.where(atr == 0, 1, atr)
    dx = 100 * np.abs(plus_di - minus_di) / np.where(plus_di + minus_di == 0, 1, plus_di + minus_di)
    adx = pd.Series(dx).rolling(period).mean().iloc[-1]
    return float(adx) if not np.isnan(adx) else 0.0


# === Multi-Indicator Confluence ===

def multi_indicator_confluence(
    rsi_val: float,
    rsi_div: str,
    macd_sig: str,
    stoch_sig: str,
    bb_sig: str,
    vwap_sig: str,
    adx: float,
) -> dict:
    """Hitung confluence dari multiple indikator.

    Returns: {"score": 0-6, "bullish": int, "bearish": int, "neutral": int}
    """
    bullish = 0
    bearish = 0
    neutral = 0

    # RSI
    if rsi_sig_label := rsi_signal(rsi_val):
        if rsi_sig_label in ("oversold", "bullish"):
            bullish += 1
        elif rsi_sig_label in ("overbought", "bearish"):
            bearish += 1
        else:
            neutral += 1

    # RSI Divergence
    if rsi_div in ("regular_bullish", "hidden_bullish"):
        bullish += 1
    elif rsi_div in ("regular_bearish", "hidden_bearish"):
        bearish += 1
    else:
        neutral += 1

    # MACD
    if macd_sig in ("bullish_cross", "bullish"):
        bullish += 1
    elif macd_sig in ("bearish_cross", "bearish"):
        bearish += 1
    else:
        neutral += 1

    # Stoch RSI
    if stoch_sig in ("oversold", "bullish_cross"):
        bullish += 1
    elif stoch_sig in ("overbought", "bearish_cross"):
        bearish += 1
    else:
        neutral += 1

    # Bollinger
    if bb_sig == "oversold":
        bullish += 1
    elif bb_sig == "overbought":
        bearish += 1
    else:
        neutral += 1

    # VWAP
    if vwap_sig == "above":
        bullish += 1
    elif vwap_sig == "below":
        bearish += 1
    else:
        neutral += 1

    total = bullish + bearish + neutral
    score = max(bullish, bearish)  # 1-6

    return {
        "score": score,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "neutral_count": neutral,
        "total": total,
    }

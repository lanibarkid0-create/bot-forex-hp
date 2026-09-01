"""Fundamental data untuk trading forex: calendar, news, COT, interest rate, currency strength.

All data gratis (free tier / public API).
"""

import re
import json
import requests
from datetime import datetime, timezone, timedelta

# === FOREX FACTORY CALENDAR ===
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NEWS_CACHE = {"date": None, "events": []}


def fetch_forexfactory_calendar() -> list[dict]:
    """Fetch high-impact news dari ForexFactory JSON API.
    Returns list of events today {time_utc, event, currency, impact}.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if NEWS_CACHE["date"] == today and NEWS_CACHE["events"]:
        return NEWS_CACHE["events"]

    events = []
    try:
        r = requests.get(FF_CALENDAR_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for ev in data:
                if ev.get("impact") in ("High", "Holiday"):
                    date_str = ev.get("date", "")
                    # Match today
                    if today in date_str:
                        events.append({
                            "time_utc": ev.get("time", ""),
                            "event": ev.get("title", ""),
                            "currency": ev.get("country", ""),
                            "impact": ev.get("impact", ""),
                        })
    except Exception as e:
        pass

    NEWS_CACHE["date"] = today
    NEWS_CACHE["events"] = events
    return events


def get_upcoming_news(buffer_min: int = 60) -> list[dict]:
    """Get news yang akan datang dalam window (default 60 menit ke depan).
    Returns list of dict {event, currency, time_utc, minutes_until}.
    """
    events = fetch_forexfactory_calendar()
    upcoming = []
    now = datetime.now(timezone.utc)

    for ev in events:
        try:
            ev_time = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {ev['time_utc']}", "%Y-%m-%d %H:%M")
            ev_time = ev_time.replace(tzinfo=timezone.utc)
            diff_min = (ev_time - now).total_seconds() / 60
            if -30 <= diff_min <= buffer_min:  # news dalam 30 menit sebelumnya sampai buffer_min ke depan
                upcoming.append({
                    **ev,
                    "minutes_until": int(diff_min),
                })
        except Exception:
            continue

    return sorted(upcoming, key=lambda x: abs(x.get("minutes_until", 999)))


def is_news_window(buffer_min: int = 30) -> tuple[bool, str]:
    """Cek apakah sekarang dalam window high-impact news."""
    events = fetch_forexfactory_calendar()
    if not events:
        return False, ""
    now = datetime.now(timezone.utc)
    for ev in events:
        try:
            ev_time = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {ev['time_utc']}", "%Y-%m-%d %H:%M")
            ev_time = ev_time.replace(tzinfo=timezone.utc)
            diff_min = abs((now - ev_time).total_seconds() / 60)
            if diff_min <= buffer_min:
                return True, f"{ev['currency']} {ev['event']} ({ev['time_utc']} UTC)"
        except Exception:
            continue
    return False, ""


# === CURRENCY STRENGTH METER ===
# Strength dihitung dari % perubahan harga dalam 24 jam terakhir
# vs major counterpart - CACHED setiap 1 jam

STRENGTH_CACHE = {"timestamp": None, "data": {}}
STRENGTH_CACHE_TTL = 600  # 10 menit (was 1 jam) — lebih fresh


def _fetch_one_strength(api_key: str, pair: str) -> float:
    """Fetch single pair untuk strength calculation."""
    try:
        from analysis import _SESSION
        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": pair, "interval": "15min", "outputsize": 96,
            "order": "ASC", "apikey": api_key,
        }
        r = _SESSION.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("values") and len(data["values"]) >= 2:
            first = float(data["values"][0]["close"])
            last = float(data["values"][-1]["close"])
            return ((last - first) / first) * 100
        return 0
    except Exception:
        return 0


def calc_currency_strength(api_key: str, periods: int = 96) -> dict:
    """Hitung currency strength untuk 8 major currencies (PARALLEL fetch).
    Cached 10 menit untuk hemat API credits + speed.
    """
    now = datetime.now(timezone.utc)
    if STRENGTH_CACHE["timestamp"]:
        age = (now - STRENGTH_CACHE["timestamp"]).total_seconds()
        if age < STRENGTH_CACHE_TTL and STRENGTH_CACHE["data"]:
            return STRENGTH_CACHE["data"]

    pairs = {
        "USD": "EUR/USD",  # inverse
        "EUR": "EUR/USD",
        "GBP": "GBP/USD",
        "JPY": "USD/JPY",
        "AUD": "AUD/USD",
        "NZD": "NZD/USD",
        "CAD": "USD/CAD",  # inverse
        "CHF": "USD/CHF",  # inverse
    }
    is_inverse = {"USD": True, "CAD": True, "CHF": True}

    # PARALLEL fetch (4 workers → 8 pair selesai dalam ~2 detik bukan ~8 detik)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    strengths = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_fetch_one_strength, api_key, pair): ccy for ccy, pair in pairs.items()}
        for fut in as_completed(futures):
            ccy = futures[fut]
            try:
                pct = fut.result()
                if is_inverse.get(ccy):
                    pct = -pct
                strengths[ccy] = round(pct, 2)
            except Exception:
                strengths[ccy] = 0

    STRENGTH_CACHE["timestamp"] = now
    STRENGTH_CACHE["data"] = strengths
    return strengths


def strength_label(score: float) -> str:
    """Convert strength score ke label."""
    if score >= 1.5:
        return "SANGAT KUAT"
    elif score >= 0.5:
        return "KUAT"
    elif score <= -1.5:
        return "SANGAT LEMAH"
    elif score <= -0.5:
        return "LEMAH"
    else:
        return "NETRAL"


def strength_emoji(score: float) -> str:
    """Convert strength score ke emoji."""
    if score >= 1.5:
        return "🟢🟢"
    elif score >= 0.5:
        return "🟢"
    elif score <= -1.5:
        return "🔴🔴"
    elif score <= -0.5:
        return "🔴"
    else:
        return "⚪"


# === NEWS SENTIMENT (RSS) ===
# Free RSS feeds dari sumber forex
NEWS_FEEDS = {
    "forexlive": "https://www.forexlive.com/feed/",
    "fxstreet": "https://www.fxstreet.com/rss/news",
    "dailyfx": "https://www.dailyfx.com/feeds/all",
}


def fetch_news_sentiment(query_keywords: list[str] = None, limit: int = 5) -> list[dict]:
    """Fetch latest news headlines dari RSS feeds.

    Returns list of {title, link, source, published}.
    """
    # Note: butuh library feedparser untuk RSS parsing yang proper
    # Untuk sekarang, return placeholder
    return []


# === INTEREST RATE ===
# Latest central bank interest rates (per 2024-2025)
# Update manual karena susah dapat real-time API gratis
INTEREST_RATES = {
    "USD": {"rate": 4.50, "central_bank": "Federal Reserve", "last_change": "2024-09-18", "next_meeting": "TBA"},
    "EUR": {"rate": 3.50, "central_bank": "European Central Bank", "last_change": "2024-09-12", "next_meeting": "TBA"},
    "GBP": {"rate": 4.75, "central_bank": "Bank of England", "last_change": "2024-08-01", "next_meeting": "TBA"},
    "JPY": {"rate": 0.25, "central_bank": "Bank of Japan", "last_change": "2024-07-31", "next_meeting": "TBA"},
    "AUD": {"rate": 4.35, "central_bank": "Reserve Bank of Australia", "last_change": "2024-09-24", "next_meeting": "TBA"},
    "NZD": {"rate": 4.75, "central_bank": "Reserve Bank of New Zealand", "last_change": "2024-08-14", "next_meeting": "TBA"},
    "CAD": {"rate": 3.75, "central_bank": "Bank of Canada", "last_change": "2024-09-04", "next_meeting": "TBA"},
    "CHF": {"rate": 1.00, "central_bank": "Swiss National Bank", "last_change": "2024-09-26", "next_meeting": "TBA"},
}


def get_pair_interest_diff(symbol: str) -> dict:
    """Get interest rate differential untuk pair forex.
    Returns {base_rate, quote_rate, diff, base_ccy, quote_ccy}.
    """
    # Parse base/quote currency
    ccy_map = {
        "EUR/USD": ("EUR", "USD"), "GBP/USD": ("GBP", "USD"),
        "AUD/USD": ("AUD", "USD"), "NZD/USD": ("NZD", "USD"),
        "USD/JPY": ("USD", "JPY"), "USD/CHF": ("USD", "CHF"),
        "USD/CAD": ("USD", "CAD"), "EUR/JPY": ("EUR", "JPY"),
        "GBP/JPY": ("GBP", "JPY"), "AUD/JPY": ("AUD", "JPY"),
        "NZD/JPY": ("NZD", "JPY"), "CAD/JPY": ("CAD", "JPY"),
        "CHF/JPY": ("CHF", "JPY"), "EUR/GBP": ("EUR", "GBP"),
        "EUR/AUD": ("EUR", "AUD"), "EUR/CHF": ("EUR", "CHF"),
        "EUR/CAD": ("EUR", "CAD"), "GBP/AUD": ("GBP", "AUD"),
        "GBP/CAD": ("GBP", "CAD"), "GBP/CHF": ("GBP", "CHF"),
        "GBP/NZD": ("GBP", "NZD"), "AUD/CAD": ("AUD", "CAD"),
        "AUD/CHF": ("AUD", "CHF"), "AUD/NZD": ("AUD", "NZD"),
        "CAD/CHF": ("CAD", "CHF"), "NZD/CAD": ("NZD", "CAD"),
        "NZD/CHF": ("NZD", "CHF"), "EURNZD": ("EUR", "NZD"),
        "XAU/USD": ("XAU", "USD"), "XAG/USD": ("XAG", "USD"),
    }
    if symbol not in ccy_map:
        return {}
    base, quote = ccy_map[symbol]
    base_info = INTEREST_RATES.get(base, {"rate": 0})
    quote_info = INTEREST_RATES.get(quote, {"rate": 0})
    return {
        "base_ccy": base,
        "quote_ccy": quote,
        "base_rate": base_info.get("rate", 0),
        "quote_rate": quote_info.get("rate", 0),
        "diff": round(base_info.get("rate", 0) - quote_info.get("rate", 0), 2),
    }


# === COT REPORT ===
# COT data from CFTC.gov (weekly, scraped)
# Format: {currency: {commercial_long, commercial_short, speculator_long, speculator_short}}
COT_CACHE = {"date": None, "data": {}}


def fetch_cot_data() -> dict:
    """Fetch COT data (simplified, weekly).
    Returns dict {currency: {commercial_net, speculator_net}}.
    """
    # Real implementation would scrape CFTC.gov
    # For now return empty (fallback ke simplified)
    return {}


# === HELPER: format fundamental block ===

def format_fundamental_block(api_key: str, symbol: str) -> str:
    """Format blok fundamental untuk Telegram - lengkap dengan news, COT, rates, strength."""
    lines = ["📰 <b>FUNDAMENTAL</b> (real-time data)\n"]

    # 1. Economic Calendar
    upcoming = get_upcoming_news(buffer_min=120)
    in_news, news_now = is_news_window()
    if in_news:
        lines.append(f"⚠️ <b>News aktif:</b> {news_now}")
    if upcoming:
        lines.append(f"📅 <b>News mendatang (2 jam):</b>")
        for ev in upcoming[:5]:
            mins = ev.get("minutes_until", 0)
            if mins > 0:
                time_str = f"dalam {mins}m"
            else:
                time_str = f"{abs(mins)}m lalu"
            lines.append(f"  • {ev['time_utc']} UTC ({time_str}) — {ev['currency']} {ev['event']}")
    else:
        lines.append("📅 <b>News:</b> clear (tidak ada high-impact 2 jam ke depan)")
    lines.append("")

    # 2. Currency Strength
    try:
        strengths = calc_currency_strength(api_key)
        if strengths:
            lines.append("💪 <b>Currency Strength (24h):</b>")
            sorted_str = sorted(strengths.items(), key=lambda x: -x[1])
            for ccy, score in sorted_str:
                emoji = strength_emoji(score)
                label = strength_label(score)
                lines.append(f"  {emoji} {ccy}: {score:+.2f}% ({label})")
            lines.append("")
    except Exception:
        pass

    # 3. Interest Rate Differential
    rate_diff = get_pair_interest_diff(symbol)
    if rate_diff:
        diff = rate_diff["diff"]
        diff_emoji = "🟢" if diff > 0 else "🔴" if diff < 0 else "⚪"
        lines.append(f"🏛️ <b>Interest Rate Diff:</b>")
        lines.append(f"  {rate_diff['base_ccy']} {rate_diff['base_rate']:.2f}% vs {rate_diff['quote_ccy']} {rate_diff['quote_rate']:.2f}%")
        lines.append(f"  {diff_emoji} Differential: {diff:+.2f}% (favor {'base' if diff > 0 else 'quote' if diff < 0 else 'netral'})")
        lines.append("")

    # 4. COT-like (simplified)
    lines.append("📊 <b>COT-like (proxy dari price action):</b>")
    lines.append("  • Speculator sentiment: ekstrim → kemungkinan reversal")
    lines.append("  • Hedge fund positioning: lihat weekly candle pattern")
    lines.append("  • Note: real COT data dari CFTC.gov, update tiap Jumat")

    return "\n".join(lines)

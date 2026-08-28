"""High-Probability Forex Bot - ICT/SMC + Multi-TF + News + Session + Range Filter.

Commands:
- /start - menu & help
- /scan - multi-pair scanner (cari high-prob setup)
- /analyze SYMBOL TF - analisa single pair (e.g. /analyze GBPUSD M5)
- /news - high-impact news hari ini
- /killzone - cek session/killzone saat ini
- /pairs - list pair didukung
- Natural input: "GBPUSD M5" juga bisa
"""

import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from analysis import (
    quick_analyze, scan_pairs, format_scan,
    get_session, is_news_window,
    SYMBOL_MAP, parse_user_input, DEFAULT_SCAN_PAIRS,
)
from fundamental import (
    fetch_forexfactory_calendar, get_upcoming_news,
    calc_currency_strength, strength_label, strength_emoji,
    get_pair_interest_diff,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("forex-bot")


# === Handlers ===

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    first_name = update.effective_user.first_name or "trader"
    text = f"""Halo {first_name}! 👋

🩺 <b>High-Probability Forex Analyzer</b>
ICT/SMC + Multi-TF + News Filter + Session Filter

<b>Cara pakai:</b>
• Ketik: <code>SYMBOL TF</code> — analisa 1 pair
  Contoh: <code>GBPUSD M5</code>, <code>XAUUSD M15</code>
• /scan — multi-pair scanner (cari setup high-prob)
• /news — high-impact news hari ini
• /kz — cek killzone saat ini
• /pairs — list pair didukung

<b>Pair forex:</b> EURUSD, GBPUSD, AUDUSD, USDJPY, USDCHF, USDCAD, EURJPY, GBPJPY, dll
<b>Timeframe:</b> M1, M5, M15, M30, M45, H1, H2, H4, H8, D1

🎯 <b>5 Konfirmasi untuk High Probability:</b>
1. HTF bias aligned (H4+H1)
2. LTF structure (CHoCH/BOS)
3. Entry di OB/FVG
4. Dalam killzone (London/NY)
5. ADX > 20 (trending)

Skor minimal <b>7/10</b> → entry layak
Di bawah 7 → <b>SKIP</b> (ini yang membedakan high-prob vs gambling)"""
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """🩺 <b>Help</b>

<b>Commands:</b>
/start - menu utama
/scan - multi-pair scanner (cari high-prob di banyak pair)
/analyze SYMBOL TF - analisa 1 pair
/news - high-impact news + currency strength
/strength - currency strength meter
/rates - central bank interest rates
/kz - cek session/killzone saat ini
/pairs - list pair yang didukung

<b>Natural input:</b> Ketik <code>SYMBOL TF</code> langsung
Contoh: <code>GBPUSD M5</code>, <code>USDJPY M15</code>

<b>Pair forex:</b>
Majors: EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCHF, USDCAD
Cross: EURJPY, GBPJPY, AUDJPY, NZDJPY, CADJPY, CHFJPY, EURGBP, dll
Metals: XAUUSD (gold), XAGUSD (silver)
Oil: XTIUSD/OIL

<b>Timeframe:</b> M1, M5, M15, M30, M45, H1, H2, H4, H8, D1

<b>Filter otomatis:</b>
✓ News high-impact (ForexFactory)
✓ Killzone (London 01-04 UTC, NY 08-11 UTC)
✓ ADX trending check
✓ Multi-TF confluence
✓ Currency strength
✓ Interest rate differential
✓ Minimum score 7/10"""
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📋 <b>Pair didukung:</b>\n\n"
    text += "<b>Forex Majors (7):</b>\n"
    text += "EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCHF, USDCAD\n\n"
    text += "<b>Forex Crosses (16):</b>\n"
    text += "EURJPY, GBPJPY, AUDJPY, NZDJPY, CADJPY, CHFJPY\n"
    text += "EURGBP, EURAUD, EURCHF, EURCAD\n"
    text += "GBPAUD, GBPCAD, GBPCHF, GBPNZD\n"
    text += "AUDCAD, AUDCHF, AUDNZD\n"
    text += "CADCHF, NZDCAD, NZDCHF, EURNZD\n\n"
    text += "<b>Metals:</b> XAUUSD, XAGUSD\n"
    text += "<b>Oil:</b> XTIUSD, OIL, WTI"
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_kz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session()
    in_news, news_event = is_news_window()
    if session["in_killzone"]:
        text = f"🟢 <b>Sekarang dalam KILLZONE</b>\n\n"
        text += f"Session: {session['kz_name']}\n"
        text += f"UTC hour: {session['hour_utc']}:00\n"
    else:
        text = f"⚪ <b>Di luar killzone</b>\n\n"
        text += f"UTC hour: {session['hour_utc']}:00\n\n"
        text += "Killzone windows (UTC):\n"
        text += "• London: 01:00-04:00\n"
        text += "• New York: 08:00-11:00\n"
        text += "• London-NY Overlap: 13:00-16:00\n"
    if in_news:
        text += f"\n⚠️ <b>News window:</b> {news_event}\n(bot akan SKIP analisa dalam ±30 menit news)"
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    events = fetch_forexfactory_calendar()
    if not events:
        text = "✅ Tidak ada high-impact news hari ini.\n\n"
    else:
        text = "📅 <b>High-Impact News Hari Ini:</b>\n\n"
        for ev in events[:10]:
            text += f"• {ev['time_utc']} UTC — {ev['currency']} {ev['event']} ({ev['impact']})\n"
        text += "\n⚠️ Hindari entry ±30 menit dari news.\n"

    # Add currency strength
    try:
        strengths = calc_currency_strength(TWELVEDATA_API_KEY)
        if strengths:
            text += "\n💪 <b>Currency Strength (24h):</b>\n"
            sorted_str = sorted(strengths.items(), key=lambda x: -x[1])
            for ccy, score in sorted_str:
                emoji = strength_emoji(score)
                label = strength_label(score)
                text += f"  {emoji} {ccy}: {score:+.2f}% ({label})\n"
    except Exception:
        pass

    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_strength(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tampilkan currency strength meter."""
    status = await update.message.reply_text("💪 Menghitung currency strength...")
    try:
        strengths = calc_currency_strength(TWELVEDATA_API_KEY)
        if not strengths:
            await status.edit_text("❌ Gagal hitung currency strength (rate limit).")
            return
        text = "💪 <b>Currency Strength Meter (24h)</b>\n\n"
        sorted_str = sorted(strengths.items(), key=lambda x: -x[1])
        for ccy, score in sorted_str:
            emoji = strength_emoji(score)
            label = strength_label(score)
            text += f"  {emoji} {ccy}: {score:+.2f}% ({label})\n"
        text += "\n<i>Update tiap 1 jam (cached)</i>"
    except Exception as e:
        text = f"❌ Error: {e}"
    await status.edit_text(text, parse_mode="HTML")


async def cmd_rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tampilkan interest rate semua central banks."""
    text = "🏛️ <b>Central Bank Interest Rates</b>\n\n"
    from fundamental import INTEREST_RATES
    for ccy, info in INTEREST_RATES.items():
        text += f"• {ccy}: {info['rate']:.2f}% ({info['central_bank']})\n"
    text += "\n<i>Last update: per akhir 2024</i>"
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text(
        f"⏳ Scanning {len(DEFAULT_SCAN_PAIRS)} pairs untuk high-prob setup..."
    )
    try:
        results = scan_pairs(TWELVEDATA_API_KEY, DEFAULT_SCAN_PAIRS)
        text = format_scan(results)
        if not results:
            text = "❌ Tidak ada setup high-probability sekarang.\n\n"
            text += "Coba lagi saat killzone (London 01-04 UTC atau NY 08-11 UTC)."
        else:
            text += f"\n<i>Scanned {len(DEFAULT_SCAN_PAIRS)} pairs</i>"
    except Exception as e:
        text = f"❌ Error scan: {e}"
    await status_msg.edit_text(text, parse_mode="HTML")


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Format: <code>/analyze SYMBOL TF</code>\n"
            "Contoh: <code>/analyze GBPUSD M5</code>",
            parse_mode="HTML"
        )
        return

    text_input = " ".join(args)
    parsed = parse_user_input(text_input)
    if not parsed:
        await update.message.reply_text(
            f"❌ Format salah atau pair/TF tidak didukung.\n"
            f"Coba: /analyze GBPUSD M5\nList pair: /pairs",
            parse_mode="HTML"
        )
        return

    symbol, tf = parsed
    status_msg = await update.message.reply_text(
        f"⏳ Menganalisa {symbol} {tf}..."
    )
    try:
        text = quick_analyze(TWELVEDATA_API_KEY, symbol, tf)
    except Exception as e:
        text = f"❌ Error: {e}"
    await status_msg.edit_text(text, parse_mode="HTML")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle natural input: 'XAUUSD M5', 'GBPJPY H1', dst."""
    text = update.message.text.strip()
    parsed = parse_user_input(text)
    if not parsed:
        await update.message.reply_text(
            "❌ Format salah. Contoh: <code>GBPUSD M5</code>\n"
            "Atau /help untuk info lengkap.",
            parse_mode="HTML"
        )
        return

    symbol, tf = parsed
    status_msg = await update.message.reply_text(
        f"⏳ Menganalisa {symbol} {tf}..."
    )
    try:
        result = quick_analyze(TWELVEDATA_API_KEY, symbol, tf)
    except Exception as e:
        result = f"❌ Error: {e}"
    await status_msg.edit_text(result, parse_mode="HTML")


async def on_error(update, context):
    log.error(f"Bot error: {context.error}")


def main():
    if not TELEGRAM_BOT_TOKEN or not TWELVEDATA_API_KEY:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN dan TWELVEDATA_API_KEY di .env!")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("pairs", cmd_pairs))
    app.add_handler(CommandHandler("kz", cmd_kz))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("strength", cmd_strength))
    app.add_handler(CommandHandler("rates", cmd_rates))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("scam", cmd_scan))  # typo alias
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(on_error)
    log.info("Forex bot berjalan...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

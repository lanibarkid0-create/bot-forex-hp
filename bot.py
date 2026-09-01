"""AI BEDAH CHART — analisa ICT/SMC otomatis (Telegram Bot).

Commands:
- /start - menu & bantuan
- /help  - bantuan lengkap
- /scan  - multi-pair scanner (cari high-prob setup)
- /analyze SYMBOL TF / /analisa SYMBOL TF - analisa 1 pair
- /news  - high-impact news hari ini
- /strength - currency strength meter
- /rates - central bank interest rates
- /kz    - cek session/killzone saat ini
- /pairs - list pair didukung
- Natural input: "GBPUSD M5" juga bisa
"""

import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
    ConversationHandler, CallbackQueryHandler,
)

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

# === Conversation states ===
STATE_CHOOSE_MODE, STATE_CHOOSE_TF = range(2)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("forex-bot")

# === Start health server (untuk Render keep-alive) ===
try:
    from health_server import start_health_server
    start_health_server()
except Exception as e:
    log.warning(f"Health server not started: {e}")


# === Pair categories (untuk /pairs) ===
PAIR_FOREX = [
    "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD",
    "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY",
    "EURGBP", "EURAUD", "EURCHF", "EURCAD",
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD",
    "AUDCAD", "AUDCHF", "AUDNZD",
    "CADCHF", "NZDCAD", "NZDCHF", "EURNZD",
]
PAIR_INDICES = [
    "NAS100", "US30", "SPX500", "DAX", "FTSE", "NIKKEI",
]
PAIR_LAINNYA = [
    "XAUUSD", "XAGUSD", "OIL",
]


# === Handlers ===

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    first_name = update.effective_user.first_name or "trader"
    text = f"""Halo {first_name}! 👋

🤖 <b>AI BEDAH CHART</b> — analisa ICT/SMC otomatis
Multi-TF • News Filter • Session Filter • Currency Strength

<b>Cara pakai:</b> ketik <b>simbol + timeframe</b>
Contoh: <code>GBPUSD M5</code>  •  <code>XAUUSD M15</code>

<b>Pair forex (utama):</b> semua mayor &amp; cross
(EURUSD, GBPUSD, AUDUSD, USDJPY, EURJPY, GBPJPY, dll)

<b>Indices:</b> NAS100, US30, SPX500, DAX, FTSE, NIKKEI
<b>Lainnya:</b> XAU, XAG, OIL

<b>Timeframe:</b> M1, M5, M15, M30, H1, H2, H4, D1

<b>Shortcut:</b>
/scan — cari setup high-prob di banyak pair
/news — high-impact news hari ini
/kz — cek killzone saat ini
/pairs — list lengkap pair
/help — bantuan"""
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """🩺 <b>Bantuan</b>

<b>Cara pakai:</b>
Ketik langsung: <code>SYMBOL TF</code>
Contoh: <code>GBPUSD M5</code>, <code>XAUUSD M15</code>

<b>Commands:</b>
/start — menu utama
/scan — multi-pair scanner
/analyze SYMBOL TF — analisa 1 pair
/analisa SYMBOL TF — alias bahasa Indonesia
/news — high-impact news + currency strength
/strength — currency strength meter
/rates — central bank interest rates
/kz — cek killzone saat ini
/pairs — list pair yang didukung

<b>Pair forex (utama):</b>
Majors: EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCHF, USDCAD
Cross: EURJPY, GBPJPY, AUDJPY, EURGBP, GBPAUD, dll

<b>Indices:</b> NAS100, US30, SPX500, DAX, FTSE, NIKKEI
<b>Lainnya:</b> XAU, XAG, OIL
<b>Timeframe:</b> M1, M5, M15, M30, H1, H2, H4, D1

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
    text = "📋 <b>Pair didukung</b>\n\n"
    text += "<b>Forex (utama):</b>\n"
    text += ", ".join(PAIR_FOREX) + "\n\n"
    text += "<b>Indices:</b>\n"
    text += ", ".join(PAIR_INDICES) + "\n\n"
    text += "<b>Lainnya:</b>\n"
    text += ", ".join(PAIR_LAINNYA) + "\n\n"
    text += "<b>Timeframe:</b>\nM1, M5, M15, M30, H1, H2, H4, D1"
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
    """Command: /analyze SYMBOL [TF] → trigger interactive flow."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Format: <code>/analyze SYMBOL [TF]</code>\n"
            "Contoh: <code>/analyze GBPUSD M5</code>\n\n"
            "Bot akan tanya <b>mode</b> (scalping/intraday/swing) "
            "lalu <b>timeframe</b> via tombol interaktif.",
            parse_mode="HTML"
        )
        return

    text_input = " ".join(args)
    # Strip mode di akhir kalau ada
    parts = text_input.split()
    if parts and parts[-1].lower() in ("scalping", "intraday", "swing"):
        text_input = " ".join(parts[:-1])

    parsed = parse_user_input(text_input)
    if not parsed:
        await update.message.reply_text(
            "❌ Format salah atau pair/TF tidak didukung.\n"
            "Coba: /analyze GBPUSD M5",
            parse_mode="HTML"
        )
        return

    symbol, tf = parsed
    # Tampilkan pilihan mode (sama seperti handle_text)
    text_msg = (
        f"📊 <b>Analisa: {symbol} · {tf}</b>\n\n"
        f"⚙️ <b>Pilih MODE trading:</b>\n"
        f"⚡ <b>Scalping</b> — 5-30 min hold\n"
        f"🎯 <b>Intraday</b> — 1-4 jam hold\n"
        f"🌊 <b>Swing</b> — 1-7 hari hold\n\n"
        f"<i>Klik salah satu tombol:</i>"
    )
    await update.message.reply_text(
        text_msg,
        parse_mode="HTML",
        reply_markup=_mode_keyboard(symbol, tf)
    )


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Info mode trading."""
    text = """⚙️ <b>Mode Trading</b>

Tambahkan mode di akhir command:
<code>GBPUSD M5 scalping</code>
<code>GBPUSD M5 intraday</code>
<code>GBPUSD M5 swing</code>

<b>⚡ Scalping</b> (M5-M15 entry, hold 5-30 menit)
• Zone width: 5 pips
• Max SL: 0.5% dari price
• TP: 1:1 / 1:1.5 / 1:2
• Cocok untuk: range kecil, news kecil

<b>🎯 Intraday</b> (M15-H1 entry, hold 1-4 jam) — DEFAULT
• Zone width: 10 pips
• Max SL: 1% dari price
• TP: 1:1 / 1:1.5 / 1:3
• Cocok untuk: London/NY session, killzone

<b>🌊 Swing</b> (H4-D1 entry, hold 1-7 hari)
• Zone width: 30 pips
• Max SL: 3% dari price
• TP: 1:2 / 1:3 / 1:5
• Cocok untuk: trend kuat, position trading

<i>Default mode = intraday</i>"""
    await update.message.reply_text(text, parse_mode="HTML")


# === INTERACTIVE FLOW: SYMBOL → MODE → TF → ANALISA ===

def _mode_keyboard(symbol: str, tf: str | None = None) -> InlineKeyboardMarkup:
    """Tombol pilihan mode trading."""
    tf_part = f"_{tf}" if tf else ""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Scalping", callback_data=f"mode:scalping:{symbol}{tf_part}"),
            InlineKeyboardButton("🎯 Intraday", callback_data=f"mode:intraday:{symbol}{tf_part}"),
            InlineKeyboardButton("🌊 Swing", callback_data=f"mode:swing:{symbol}{tf_part}"),
        ]
    ])


def _tf_keyboard(symbol: str, mode: str) -> InlineKeyboardMarkup:
    """Tombol pilihan timeframe."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("M1", callback_data=f"tf:M1:{symbol}:{mode}"),
            InlineKeyboardButton("M5", callback_data=f"tf:M5:{symbol}:{mode}"),
            InlineKeyboardButton("M15", callback_data=f"tf:M15:{symbol}:{mode}"),
            InlineKeyboardButton("M30", callback_data=f"tf:M30:{symbol}:{mode}"),
        ],
        [
            InlineKeyboardButton("H1", callback_data=f"tf:H1:{symbol}:{mode}"),
            InlineKeyboardButton("H2", callback_data=f"tf:H2:{symbol}:{mode}"),
            InlineKeyboardButton("H4", callback_data=f"tf:H4:{symbol}:{mode}"),
            InlineKeyboardButton("D1", callback_data=f"tf:D1:{symbol}:{mode}"),
        ],
        [
            InlineKeyboardButton("❌ Batal", callback_data=f"cancel:{symbol}:{mode}"),
        ]
    ])


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: user ketik symbol (dengan/tanpa TF) → tampilkan pilihan mode."""
    text = update.message.text.strip()

    # Strip mode jika ada di akhir (backward compat)
    parts = text.split()
    if parts and parts[-1].lower() in ("scalping", "intraday", "swing"):
        # Mode diberikan → tanya TF
        mode = parts[-1].lower()
        text = " ".join(parts[:-1])
        parsed = parse_user_input(text)
        if not parsed:
            await update.message.reply_text(
                "❌ Format salah. Contoh: <code>GBPUSD M5</code>",
                parse_mode="HTML"
            )
            return ConversationHandler.END
        symbol, _ = parsed
        await update.message.reply_text(
            f"📊 <b>{symbol}</b>\n\nPilih <b>timeframe</b> untuk mode {mode.upper()}:",
            parse_mode="HTML",
            reply_markup=_tf_keyboard(symbol, mode)
        )
        return ConversationHandler.END

    # Standar: cuma symbol atau symbol+TF → tanya MODE
    parsed = parse_user_input(text)
    if not parsed:
        await update.message.reply_text(
            "❌ Format salah. Contoh: <code>GBPUSD M5</code>\n"
            "Atau /help untuk info lengkap.",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    symbol, tf = parsed
    # Simpan ke context untuk flow
    context.user_data["pending_symbol"] = symbol
    context.user_data["pending_tf"] = tf

    mode_emoji = {"scalping": "⚡", "intraday": "🎯", "swing": "🌊"}
    mode_desc = {
        "scalping": "5-30 min hold · 5 pips zone · 0.5% SL",
        "intraday": "1-4 jam hold · 10 pips zone · 1% SL",
        "swing": "1-7 hari hold · 30 pips zone · 3% SL",
    }
    text_msg = (
        f"📊 <b>Analisa: {symbol} · {tf}</b>\n\n"
        f"⚙️ <b>Pilih MODE trading:</b>\n"
        f"⚡ <b>Scalping</b> — {mode_desc['scalping']}\n"
        f"🎯 <b>Intraday</b> — {mode_desc['intraday']}\n"
        f"🌊 <b>Swing</b> — {mode_desc['swing']}\n\n"
        f"<i>Klik salah satu tombol di bawah:</i>"
    )
    await update.message.reply_text(
        text_msg,
        parse_mode="HTML",
        reply_markup=_mode_keyboard(symbol, tf)
    )
    return ConversationHandler.END


async def on_mode_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: user klik tombol mode → tanya TF (atau langsung analisa kalau TF sudah ada)."""
    query = update.callback_query
    await query.answer()

    # Parse callback_data: "mode:scalping:EURUSD_M5" atau "mode:scalping:EURUSD"
    parts = query.data.split(":")
    if len(parts) < 3:
        return
    mode = parts[1]
    sym_tf = parts[2]

    if "_" in sym_tf:
        # Sudah ada TF → langsung analisa
        symbol, tf = sym_tf.split("_", 1)
        await _run_analyze(query, context, symbol, tf, mode)
    else:
        # Tanya TF
        symbol = sym_tf
        context.user_data["pending_symbol"] = symbol
        context.user_data["pending_mode"] = mode
        mode_label = {"scalping": "⚡ Scalping", "intraday": "🎯 Intraday", "swing": "🌊 Swing"}.get(mode, mode)
        tf_desc = {
            "scalping": "M1-M15 disarankan",
            "intraday": "M5-H1 disarankan",
            "swing": "H1-D1 disarankan",
        }
        await query.edit_message_text(
            f"📊 <b>{symbol}</b> · {mode_label}\n\n"
            f"⏰ <b>Pilih TIMEFRAME:</b>\n"
            f"<i>{tf_desc.get(mode, '')}</i>",
            parse_mode="HTML",
            reply_markup=_tf_keyboard(symbol, mode)
        )


async def on_tf_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: user klik tombol TF → jalankan analisa."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    if len(parts) < 4:
        return
    tf = parts[1]
    symbol = parts[2]
    mode = parts[3]
    await _run_analyze(query, context, symbol, tf, mode)


async def on_cancel_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: user klik Batal."""
    query = update.callback_query
    await query.answer("Dibatalkan")
    await query.edit_message_text(
        "❌ Analisa dibatalkan.\n\nKetik symbol lagi (contoh: <code>EURUSD M5</code>) untuk mulai.",
        parse_mode="HTML"
    )


async def _run_analyze(query, context, symbol, tf, mode):
    """Helper: jalankan analisa & edit message dengan hasilnya."""
    from analysis import SymbolPlanError, SymbolNotFoundError

    mode_emoji = {"scalping": "⚡", "intraday": "🎯", "swing": "🌊"}.get(mode, "🎯")

    # Tampilkan status "loading"
    await query.edit_message_text(
        f"⏳ {mode_emoji} Menganalisa <b>{symbol} {tf}</b> ({mode})...\n\n"
        f"<i>Fetching 6 timeframe (D1, H4, H1, M30, M15, M5)...</i>",
        parse_mode="HTML"
    )

    try:
        text = quick_analyze(TWELVEDATA_API_KEY, symbol, tf, mode)
    except SymbolPlanError as e:
        # Symbol butuh plan upgrade → fallback ke forex pair
        await query.edit_message_text(
            f"⚠️ <b>{symbol}</b> tidak tersedia di free plan TwelveData.\n\n"
            f"<b>Alternatif (free, sudah teruji):</b>\n"
            f"• Forex majors: EURUSD, GBPUSD, USDJPY, AUDUSD\n"
            f"• Metals: XAUUSD, XAGUSD\n"
            f"• Crypto: BTC, ETH\n\n"
            f"<i>Pair indices (NAS100, US30, SPX500) butuh plan Grow/Venture (~$29/bln).</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💶 EURUSD", callback_data=f"mode:{mode}:EURUSD"),
                    InlineKeyboardButton("💷 GBPUSD", callback_data=f"mode:{mode}:GBPUSD"),
                    InlineKeyboardButton("🥇 XAUUSD", callback_data=f"mode:{mode}:XAUUSD"),
                ],
                [
                    InlineKeyboardButton("💴 USDJPY", callback_data=f"mode:{mode}:USDJPY"),
                    InlineKeyboardButton("🥈 XAGUSD", callback_data=f"mode:{mode}:XAGUSD"),
                    InlineKeyboardButton("🪙 BTC", callback_data=f"mode:{mode}:BTC"),
                ]
            ])
        )
        return
    except SymbolNotFoundError as e:
        await query.edit_message_text(
            f"❌ <b>{symbol}</b> tidak ditemukan di TwelveData.\n\n"
            f"Ketik <code>/pairs</code> untuk lihat pair yang didukung.",
            parse_mode="HTML"
        )
        return
    except Exception as e:
        error_msg = str(e)
        if "credits" in error_msg.lower() or "rate" in error_msg.lower():
            text = (
                f"⏳ <b>Rate limit TwelveData</b>\n\n"
                f"Free tier = 8 API/menit. Sudah kena limit.\n\n"
                f"<b>Solusi:</b>\n"
                f"• Tunggu 60 detik lalu coba lagi\n"
                f"• Cache 60 detik sudah aktif, jadi analisa kedua akan lebih cepat\n"
                f"• Upgrade TwelveData ke paid plan untuk tanpa limit"
            )
        else:
            text = f"❌ Error: {e}"

        await query.edit_message_text(text, parse_mode="HTML")
        return

    # Sukses — kirim hasil (split kalau terlalu panjang)
    try:
        await query.edit_message_text(
            f"{mode_emoji} <b>{symbol} {tf}</b> ({mode})\n\n{text}",
            parse_mode="HTML"
        )
    except Exception:
        # Kalau pesan terlalu panjang, kirim baru
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            parse_mode="HTML"
        )
        try:
            await query.delete_message()
        except Exception:
            pass


async def on_error(update, context):
    log.error(f"Bot error: {context.error}")


def main():
    if not TELEGRAM_BOT_TOKEN or not TWELVEDATA_API_KEY:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN dan TWELVEDATA_API_KEY di .env!")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # === Command handlers ===
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
    app.add_handler(CommandHandler("analisa", cmd_analyze))  # ID alias
    app.add_handler(CommandHandler("mode", cmd_mode))

    # === Interactive flow: callback dari inline button ===
    app.add_handler(CallbackQueryHandler(on_mode_click, pattern=r"^mode:"))
    app.add_handler(CallbackQueryHandler(on_tf_click, pattern=r"^tf:"))
    app.add_handler(CallbackQueryHandler(on_cancel_click, pattern=r"^cancel:"))

    # === Natural text input (symbol detection) ===
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_error_handler(on_error)
    log.info("AI BEDAH CHART berjalan... (interactive mode)")

    # === Run polling dengan auto-retry kalau koneksi putus ===
    import time as _time
    while True:
        try:
            app.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
                poll_interval=2.0,      # jeda antar poll
                timeout=30,             # long polling timeout
                bootstrap_retries=5,    # retry saat startup
            )
            break  # normal exit
        except KeyboardInterrupt:
            log.info("Dihentikan manual")
            break
        except Exception as e:
            log.error(f"Polling crash: {e}. Restart dalam 10 detik...")
            _time.sleep(10)
            # continue loop → restart polling
            continue


if __name__ == "__main__":
    main()

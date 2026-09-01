# 🤖 AI BEDAH CHART — Telegram Bot

Bot Telegram untuk analisa forex/gold/indices dengan ICT/SMC + Multi-TF + Fundamental.

**Fitur:**
- 🎯 6-Timeframe analysis (D1, H4, H1, M30, M15, M5)
- 📍 Area zona entry detail (OB, FVG, Swing) di M5
- ⚙️ 3 mode trading (Scalping / Intraday / Swing)
- 📊 Interactive flow dengan inline button
- 🛡️ Risk management (SL/TP otomatis)
- 📰 Fundamental filter (news, currency strength, interest rate)
- 🌐 24/7 online dengan Render free tier

---

## 🚀 Quick Start (Deploy 5 menit)

### 1. Push ke GitHub
```bash
cd /home/lani/Dokumen/bot-forex
./deploy.sh
```

Atau manual:
```bash
git init
git add .
git commit -m "AI BEDAH CHART"
git branch -M main
git remote add origin https://github.com/USERNAME/bot-forex.git
git push -u origin main
```

### 2. Deploy ke Render
1. Buka https://render.com → Sign up dengan GitHub
2. **New +** → **Blueprint**
3. Pilih repo `bot-forex`
4. Isi environment variables:
   - `TELEGRAM_BOT_TOKEN` (dari .env)
   - `TWELVEDATA_API_KEY` (dari .env)
5. **Apply** → tunggu build (~2-3 menit)
6. ✅ **Live 24/7!**

---

## 💻 Local Development

### Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env  # isi TELEGRAM_BOT_TOKEN & TWELVEDATA_API_KEY
```

### Run
```bash
python3 bot.py
```

Bot akan jalan di:
- Telegram polling (port dinamis)
- Health server: http://localhost:8080/health

---

## 📱 Cara Pakai

### Di Telegram, chat `@your_bot`:

**Basic:**
- `/start` — menu
- `/help` — bantuan
- `/pairs` — list pair
- `/scan` — multi-pair scanner
- `/news` — high-impact news

**Analisa interaktif:**
- Ketik `EURUSD` → pilih mode → pilih TF → hasil
- Ketik `XAUUSD M5` → pilih mode → hasil
- `/analyze GBPUSD H1 swing` → langsung (skip mode)

**Mode trading:**
| Mode | Hold | Zone | SL | TP |
|---|---|---|---|---|
| ⚡ Scalping | 5-30 min | 5 pips | 0.5% | 1:1 / 1:1.5 / 1:2 |
| 🎯 Intraday | 1-4 jam | 10 pips | 1% | 1:1 / 1:1.5 / 1:3 |
| 🌊 Swing | 1-7 hari | 30 pips | 3% | 1:2 / 1:3 / 1:5 |

---

## 🗂️ Struktur File

```
bot-forex/
├── bot.py              # Main bot + handlers + interactive flow
├── analysis.py         # Multi-TF analysis engine
├── indicators.py       # RSI, MACD, Bollinger, dll
├── fundamental.py      # News, currency strength, rates
├── health_server.py    # HTTP /health untuk Render keep-alive
├── Dockerfile          # Production container
├── render.yaml         # Render Blueprint
├── railway.json        # Railway config
├── requirements.txt    # Python dependencies
├── deploy.sh           # Git push helper
├── run.sh              # Local launcher
├── .env.example        # Env template
├── .gitignore          # Git ignore
└── README.md           # This file
```

---

## 🛠️ API Requirements

### Telegram Bot Token
1. Chat [@BotFather](https://t.me/BotFather) di Telegram
2. `/newbot` → kasih nama & username
3. Copy token

### TwelveData API Key
1. Daftar di [twelvedata.com](https://twelvedata.com)
2. Free tier: **8 API/menit, 800/hari**
3. Copy API key dari dashboard

> **Catatan:** Pair indices (NAS100, US30, SPX500) butuh plan **Grow ($29/bln)**.
> Free tier support: Forex majors/cross, XAUUSD, XAGUSD, OIL, BTC, ETH.

---

## 🔧 Troubleshooting

### Bot tidak respond
```bash
# Cek log di Render dashboard → Logs
# Atau test lokal:
cd /home/lani/Dokumen/bot-forex
python3 bot.py
```

### Rate limit error
- Free tier TwelveData = 8/menit
- Bot sudah ada auto-retry + cache 60 detik
- Solusi: upgrade TwelveData, atau tunggu 1 menit

### Health check gagal
```bash
# Test lokal
curl http://127.0.0.1:8080/health
# Expected: {"status":"ok","uptime_sec":N}
```

---

## 📊 Limits & Costs

| Service | Free Tier | Paid |
|---|---|---|
| **Render** | 750 jam/bulan | $7/bln always-on |
| **Railway** | $5 credit/bulan | $5+ usage |
| **Telegram** | Unlimited | Free |
| **TwelveData** | 8 req/menit | $29/bln 800 req/menit |

**Total biaya: $0/bulan** (cukup untuk personal use)

---

## ⚠️ Disclaimer

Bot ini adalah **alat bantu analisa**, BUKAN sinyal finansial resmi.
- Selalu konfirmasi dengan analisa manual
- Atur risk management sendiri (max 1-2% per trade)
- Test dulu di demo account
- Developer tidak bertanggung jawab atas kerugian trading

---

## 📜 License

MIT — bebas dipakai, dimodifikasi, didistribusikan.

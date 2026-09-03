#!/bin/bash
# Restart bot dengan token baru
# Usage: ./restart.sh

set -e
cd "$(dirname "$0")"

echo "🤖 AI BEDAH CHART - Restart Bot"
echo "================================"

# Kill existing
if pgrep -f "python3 bot.py" > /dev/null; then
    echo "🛑 Stop existing bot..."
    pkill -9 -f "python3 bot.py" || true
    sleep 2
fi

# Validasi .env
if [ ! -f .env ]; then
    echo "❌ File .env tidak ada!"
    exit 1
fi

# Validasi token
echo "🔑 Validating token..."
python3 -c "
from dotenv import load_dotenv
import os, requests
load_dotenv()
token = os.getenv('TELEGRAM_BOT_TOKEN', '')
r = requests.get(f'https://api.telegram.org/bot{token}/getMe', timeout=10)
if r.status_code == 200:
    data = r.json()
    bot = data['result']
    print(f'  ✅ Token valid: @{bot[\"username\"]} (ID: {bot[\"id\"]})')
else:
    print(f'  ❌ Token INVALID: {r.text[:200]}')
    print('  → Update token di .env lalu jalankan ulang')
    exit(1)
" || exit 1

# Start bot
echo ""
echo "🚀 Starting bot..."
nohup python3 bot.py > bot.log 2>&1 &
BOT_PID=$!
sleep 4

# Verify
if ps -p $BOT_PID > /dev/null; then
    echo "✅ Bot RUNNING (PID $BOT_PID)"
    echo ""
    echo "📊 Log:"
    head -10 bot.log
    echo ""
    echo "🩺 Health check:"
    curl -s http://127.0.0.1:8080/health || echo "  (health check via /health)"
    echo ""
    echo "📱 Test di Telegram: chat @lani1_bot, kirim /start"
else
    echo "❌ Bot MATI setelah start. Cek log:"
    tail -20 bot.log
    exit 1
fi

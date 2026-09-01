#!/bin/bash
# AI BEDAH CHART - launcher script
# Usage: ./run.sh
set -e

cd "$(dirname "$0")"

# Kill existing bot.py kalau ada
if pgrep -f "python3? bot.py" > /dev/null; then
    echo "⚠️  Ada bot.py masih jalan, kill dulu..."
    pkill -f "python3? bot.py" || true
    sleep 1
fi

# Validasi .env
if [ ! -f .env ]; then
    echo "❌ File .env tidak ada. Buat dulu:"
    echo "   TELEGRAM_BOT_TOKEN=..."
    echo "   TWELVEDATA_API_KEY=..."
    exit 1
fi

# Cek dependency
python3 -c "import telegram, pandas, numpy, requests, dotenv" 2>/dev/null || {
    echo "❌ Dependency belum lengkap. Install:"
    echo "   pip install -r requirements.txt"
    exit 1
}

echo "🤖 AI BEDAH CHART starting..."
exec python3 bot.py

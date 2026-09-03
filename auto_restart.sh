#!/bin/bash
# ============================================
# AI BEDAH CHART - Auto-restart Setup (no sudo)
# ============================================
# Pakai systemd --user (per-user service) yang:
# ✅ Auto-start saat login (kalau loginctl enable-linger)
# ✅ Auto-restart kalau crash
# ✅ Tidak perlu sudo
#
# Fallback: crontab @reboot (kalau systemd --user tidak enable)
# ============================================

set -e
cd "$(dirname "$0")"

echo "🤖 AI BEDAH CHART - Auto-restart Setup"
echo "========================================"

# 1. Cek python3-venv, kalau tidak ada pakai system python
if ! python3 -m venv --help > /dev/null 2>&1; then
    echo "⚠️  python3-venv tidak terinstall, pakai system python"
    USE_VENV=0
elif [ ! -d .venv ]; then
    echo "📦 Creating venv..."
    if python3 -m venv .venv 2>/dev/null; then
        USE_VENV=1
        if [ -f .venv/bin/pip ]; then
            .venv/bin/pip install --upgrade pip --quiet
            .venv/bin/pip install -r requirements.txt --quiet
        fi
        echo "✅ venv ready"
    else
        echo "⚠️  venv creation failed, pakai system python"
        USE_VENV=0
    fi
else
    USE_VENV=1
    echo "✅ venv exists"
fi

# 2. Validasi .env
if [ ! -f .env ]; then
    echo "❌ File .env tidak ada!"
    exit 1
fi
echo "✅ .env exists"

# 3. Cek apakah systemd --user jalan
echo ""
echo "🔍 Checking systemd --user availability..."
if systemctl --user status > /dev/null 2>&1; then
    USE_SYSTEMD=1
    echo "✅ systemd --user available"
else
    USE_SYSTEMD=0
    echo "⚠️  systemd --user not running, will use crontab fallback"
fi

# 4. Setup systemd --user service
if [ "$USE_SYSTEMD" = "1" ]; then
    echo ""
    echo "📋 Installing systemd --user service..."

    mkdir -p ~/.config/systemd/user
    cp systemd/ai-bedah-chart-user.service ~/.config/systemd/user/ai-bedah-chart.service

    # Enable linger supaya service jalan walaupun tidak login
    if command -v loginctl > /dev/null 2>&1; then
        loginctl enable-linger "$USER" 2>/dev/null || echo "  (loginctl enable-linger skipped - OK)"
    fi

    systemctl --user daemon-reload
    systemctl --user enable ai-bedah-chart.service
    systemctl --user restart ai-bedah-chart.service

    sleep 3
    echo ""
    echo "📊 Service status:"
    systemctl --user status ai-bedah-chart.service --no-pager | head -20
fi

# 5. Setup crontab fallback (ALWAYS, sebagai backup)
echo ""
echo "🔧 Setting up crontab @reboot fallback..."

# Kill existing bot
pkill -9 -f "python3 bot.py" 2>/dev/null || true
pkill -9 -f "watch_loop" 2>/dev/null || true
sleep 2

# Tambah crontab entries (no duplicate)
CRON_LINE="@reboot sleep 30 && /home/lani/Dokumen/bot-forex/auto_start.sh >> /home/lani/Dokumen/bot-forex/bot.log 2>&1"
CRON_WATCH="@reboot sleep 60 && /home/lani/Dokumen/bot-forex/watch_loop.sh >> /home/lani/Dokumen/bot-forex/watch.log 2>&1"

# Backup crontab
crontab -l > /tmp/cron.bak 2>/dev/null || true

# Hapus entry lama kalau ada
crontab -l 2>/dev/null | grep -v "auto_start.sh\|watch_loop.sh" > /tmp/cron.new || true

# Tambah entry baru
echo "$CRON_LINE" >> /tmp/cron.new
echo "$CRON_WATCH" >> /tmp/cron.new
crontab /tmp/cron.new
rm /tmp/cron.new

echo "✅ crontab installed"

# 6. Start sekarang
echo ""
echo "🚀 Starting bot now..."
if [ "$USE_VENV" = "1" ] && [ -x .venv/bin/python ]; then
    nohup .venv/bin/python bot.py > bot.log 2>&1 &
else
    nohup python3 bot.py > bot.log 2>&1 &
fi
sleep 4

# 7. Verify
if pgrep -f "python3 bot.py" > /dev/null; then
    echo "✅ Bot RUNNING!"
    echo ""
    echo "📱 Test di Telegram: chat @lani1_bot, kirim /start"
    echo ""
    echo "📌 Perintah berguna:"
    echo "   ./restart.sh         # restart manual"
    echo "   ./status.sh          # cek status"
    echo "   tail -f bot.log      # lihat log real-time"
    echo "   systemctl --user status ai-bedah-chart   # cek systemd"
else
    echo "❌ Bot GAGAL start. Cek log:"
    tail -20 bot.log
    exit 1
fi

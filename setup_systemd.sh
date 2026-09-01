#!/bin/bash
# ============================================
# Setup systemd service untuk auto-start bot
# ============================================
# Usage: sudo ./setup_systemd.sh

set -e

SERVICE_NAME="ai-bedah-chart"
SERVICE_FILE="$(dirname "$0")/systemd/ai-bedah-chart.service"
TARGET="/etc/systemd/system/${SERVICE_NAME}.service"

if [ "$EUID" -ne 0 ]; then
    echo "❌ Harus run sebagai root (sudo)"
    exit 1
fi

if [ ! -f "$SERVICE_FILE" ]; then
    echo "❌ File service tidak ada: $SERVICE_FILE"
    exit 1
fi

# 1. Buat venv kalau belum ada
cd /home/lani/Dokumen/bot-forex
if [ ! -d .venv ]; then
    echo "📦 Creating venv..."
    sudo -u lani python3 -m venv .venv
    sudo -u lani .venv/bin/pip install -r requirements.txt
fi

# 2. Copy service file
echo "📋 Installing service file..."
cp "$SERVICE_FILE" "$TARGET"

# 3. Reload systemd
echo "🔄 Reloading systemd..."
systemctl daemon-reload

# 4. Enable (auto-start on boot)
echo "✅ Enabling service..."
systemctl enable "$SERVICE_NAME"

# 5. Stop existing process kalau ada
pkill -9 -f "python3 bot.py" 2>/dev/null || true
sleep 2

# 6. Start service
echo "🚀 Starting service..."
systemctl start "$SERVICE_NAME"
sleep 3

# 7. Status
echo ""
echo "==================================="
echo "📊 Service status:"
echo "==================================="
systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "✅ Bot terinstall sebagai systemd service!"
echo ""
echo "📌 Perintah berguna:"
echo "   sudo systemctl status $SERVICE_NAME    # cek status"
echo "   sudo systemctl stop $SERVICE_NAME      # stop"
echo "   sudo systemctl restart $SERVICE_NAME   # restart"
echo "   sudo journalctl -u $SERVICE_NAME -f    # lihat log real-time"
echo "   sudo systemctl disable $SERVICE_NAME   # disable auto-start"
echo ""

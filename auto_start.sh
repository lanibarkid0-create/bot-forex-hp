#!/bin/bash
# Auto-start script - dipanggil oleh crontab @reboot
# Tunggu 30 detik untuk network ready, lalu start bot

cd /home/lani/Dokumen/bot-forex

# Tunggu network ready
sleep 30

# Kill any existing
pkill -9 -f "python3 bot.py" 2>/dev/null || true
sleep 2

# Start bot dengan nohup
if [ -x .venv/bin/python ]; then
    nohup .venv/bin/python bot.py >> bot.log 2>&1 &
else
    nohup python3 bot.py >> bot.log 2>&1 &
fi
echo "[auto_start] Bot started at $(date)" >> bot.log

#!/bin/bash
# Watch loop - kalau bot mati, restart otomatis
# Run via crontab @reboot atau systemd
# Loop: cek tiap 30 detik, restart kalau mati

cd /home/lani/Dokumen/bot-forex

while true; do
    if ! pgrep -f "python3 bot.py" > /dev/null; then
        echo "[$(date)] Bot mati, restarting..." >> watch.log
        pkill -9 -f "python3 bot.py" 2>/dev/null
        sleep 2
        nohup python3 bot.py >> bot.log 2>&1 &
    fi
    sleep 30
done

#!/bin/bash
# Cek status bot
cd "$(dirname "$0")"

echo "🤖 AI BEDAH CHART - Status"
echo "==========================="
echo ""

# Proses
if pgrep -f "python3 bot.py" > /dev/null; then
    PID=$(pgrep -f "python3 bot.py" | head -1)
    echo "✅ Bot RUNNING (PID $PID)"
    ps -p $PID -o pid,pcpu,pmem,etime,cmd | tail -1
else
    echo "❌ Bot MATI"
fi

echo ""
echo "🩺 Health check:"
curl -s --max-time 3 http://127.0.0.1:8080/health 2>/dev/null || echo "  (health server not responding)"

echo ""
echo "📊 Systemd user service:"
if systemctl --user is-active ai-bedah-chart > /dev/null 2>&1; then
    echo "  ✅ Active"
else
    echo "  ⚠️  Not active"
fi

echo ""
echo "⏰ Crontab entries:"
crontab -l 2>/dev/null | grep -E "auto_start|watch_loop" || echo "  (no crontab entries)"

echo ""
echo "📜 Last 5 log lines:"
tail -5 bot.log 2>/dev/null || echo "  (no log)"

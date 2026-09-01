#!/bin/bash
# ============================================
# AI BEDAH CHART - Deploy ke GitHub + Render
# ============================================
# Usage: ./deploy.sh
# Syarat: git installed, sudah login GitHub

set -e
cd "$(dirname "$0")"

echo "🤖 AI BEDAH CHART - Deploy Script"
echo "=================================="
echo ""

# 1. Validasi
if [ ! -f .env ]; then
    echo "❌ File .env tidak ada!"
    echo "   Buat dulu: cp .env.example .env  (lalu isi token)"
    exit 1
fi

if ! command -v git &> /dev/null; then
    echo "❌ Git belum terinstall. Install: sudo apt install git"
    exit 1
fi

# 2. Cek apakah sudah jadi git repo
if [ ! -d .git ]; then
    echo "📦 Initialize git repository..."
    git init
    git branch -M main
fi

# 3. Tambah semua file
echo "📝 Menambah file..."
git add .

# 4. Commit
echo "💾 Commit..."
git commit -m "AI BEDAH CHART - $(date '+%Y-%m-%d %H:%M')" || echo "   (tidak ada perubahan)"

# 5. Cek remote
if ! git remote get-url origin &> /dev/null; then
    echo ""
    echo "⚠️  Belum ada remote origin!"
    echo "   Buat repo di https://github.com/new dulu, lalu jalankan:"
    echo "   git remote add origin https://github.com/USERNAME/REPO.git"
    echo ""
    read -p "Atau paste URL repo GitHub kamu sekarang: " REPO_URL
    if [ -n "$REPO_URL" ]; then
        git remote add origin "$REPO_URL"
    else
        echo "❌ Batal. Jalankan ulang setelah setup remote."
        exit 1
    fi
fi

# 6. Push
echo "🚀 Push ke GitHub..."
git push -u origin main 2>&1 || git push -u origin master

echo ""
echo "✅ Selesai! Code sudah di GitHub."
echo ""
echo "=============================================="
echo "📌 LANGKAH SELANJUTNYA (deploy ke Render):"
echo "=============================================="
echo "1. Buka https://render.com → Sign up dengan GitHub"
echo "2. Klik 'New +' → 'Blueprint'"
echo "3. Pilih repo 'bot-forex' kamu"
echo "4. Render otomatis baca render.yaml"
echo "5. Isi Environment Variables:"
echo "   • TELEGRAM_BOT_TOKEN = (dari .env)"
echo "   • TWELVEDATA_API_KEY = (dari .env)"
echo "6. Klik 'Apply' → tunggu 2-3 menit"
echo "7. Bot LIVE 24/7! 🎉"
echo ""

#!/bin/bash
# ============================================================
# update_vps.sh — Обновление бота на VPS (запускать после git push)
# Запускать на VPS: bash update_vps.sh
# ============================================================
BOT_DIR="/opt/chimera_bot"
SERVICE_NAME="chimera_bot"

echo "=== Останавливаем бот ==="
systemctl stop $SERVICE_NAME

echo "=== Обновляем код ==="
cd $BOT_DIR
git pull origin master

echo "=== Обновляем зависимости ==="
source venv/bin/activate
pip install -r requirements.txt -q

echo "=== Запускаем бот ==="
systemctl start $SERVICE_NAME
sleep 3
systemctl status $SERVICE_NAME --no-pager

echo "✅ Обновление завершено"
echo "   Логи: journalctl -u $SERVICE_NAME -f"

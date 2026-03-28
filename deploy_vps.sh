#!/bin/bash
# ============================================================
# deploy_vps.sh — Деплой Chimera AI Bot на Ubuntu VPS
# Запускать: bash deploy_vps.sh
# ============================================================
set -e

BOT_DIR="/opt/chimera_bot"
BOT_USER="chimera"
SERVICE_NAME="chimera_bot"
PYTHON="python3"

echo "=== [1/7] Обновляем систему ==="
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv nodejs npm git curl screen

echo "=== [2/7] Создаём системного пользователя ==="
id -u $BOT_USER &>/dev/null || useradd -m -s /bin/bash $BOT_USER

echo "=== [3/7] Копируем файлы бота ==="
mkdir -p $BOT_DIR
# Копируем всё кроме .db и лог-файлов (они создадутся заново)
rsync -av --exclude='*.db' --exclude='*.log' --exclude='__pycache__' \
      --exclude='.git' --exclude='*.pyc' \
      ./ $BOT_DIR/

chown -R $BOT_USER:$BOT_USER $BOT_DIR

echo "=== [4/7] Устанавливаем зависимости Python ==="
cd $BOT_DIR
$PYTHON -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "=== [5/7] Устанавливаем зависимости Node.js ==="
npm install --prefix $BOT_DIR --silent

echo "=== [6/7] Создаём systemd сервис ==="
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=Chimera AI Betting Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$BOT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONIOENCODING=utf-8
ExecStart=$BOT_DIR/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "=== [7/7] Запускаем бот ==="
systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl restart $SERVICE_NAME

sleep 3
systemctl status $SERVICE_NAME --no-pager

echo ""
echo "✅ Деплой завершён!"
echo "   Логи:   journalctl -u $SERVICE_NAME -f"
echo "   Стоп:   systemctl stop $SERVICE_NAME"
echo "   Старт:  systemctl start $SERVICE_NAME"
echo "   Статус: systemctl status $SERVICE_NAME"

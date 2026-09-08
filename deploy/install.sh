#!/usr/bin/env bash
# Установка бота на Ubuntu 22.04+ (без Docker): зависимости, venv, .env
# Запускать из любой папки репозитория: bash deploy/install.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "== Системные пакеты =="
sudo apt update
sudo apt install -y python3-venv python3-pip ffmpeg git

echo "== Виртуальное окружение =="
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

echo "== Конфигурация .env =="
if [ ! -f .env ]; then
    cp .env.example .env
    echo "!! .env создан из шаблона — впиши DISCORD_TOKEN перед запуском"
fi
# на Linux ffmpeg доступен в PATH
sed -i 's|^FFMPEG_PATH=.*|FFMPEG_PATH=ffmpeg|' .env
grep -q '^FFMPEG_PATH=' .env || echo 'FFMPEG_PATH=ffmpeg' >> .env

echo
echo "Готово. Проверка запуска:   venv/bin/python bot.py"
echo "Служба (автозапуск):        sudo cp deploy/discordbot.service /etc/systemd/system/"
echo "                            sudo systemctl daemon-reload"
echo "                            sudo systemctl enable --now discordbot"
echo "Логи службы:                journalctl -u discordbot -f"

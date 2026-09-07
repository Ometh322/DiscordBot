"""Загрузка конфигурации из .env и общие пути проекта."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SOUNDS_DIR = DATA_DIR / "sounds"
DB_PATH = DATA_DIR / "db.sqlite"
BINDINGS_PATH = DATA_DIR / "bindings.json"

load_dotenv(BASE_DIR / ".env")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
VK_TOKEN = os.getenv("VK_TOKEN", "").strip()

# User-Agent клиента Kate Mobile — обязателен для методов audio.*
# (заполняется скриптом scripts/get_vk_token.py, вручную не менять)
VK_USER_AGENT = os.getenv("VK_USER_AGENT", "").strip()
VK_API_VERSION = os.getenv("VK_API_VERSION", "").strip() or "5.131"

# Путь к FFmpeg; по умолчанию — из PATH (работает после перезапуска системы).
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg").strip()


def ensure_dirs() -> None:
    """Создаёт служебные каталоги (data/, data/sounds/)."""
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)

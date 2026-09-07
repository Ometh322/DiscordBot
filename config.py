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

# Путь к FFmpeg; по умолчанию — из PATH (работает после перезапуска системы).
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg").strip()


SOUNDS_README = """\
Персональные звуки приветствия (data/sounds)

Положи сюда аудиофайл, названный одним из способов:
  <user_id>.mp3      — ID пользователя Discord (ПКМ по профилю -> Копировать ID)
  <username>.mp3     — логин в нижнем регистре, без пробелов
  <display_name>.mp3 — отображаемое имя в нижнем регистре, без пробелов

Форматы: mp3, ogg, wav, m4a, flac, opus.

Когда файл проиграется:
  - участник заходит в голосовой канал (бот подключается, играет и выходит);
  - команда /hello — твой файл, а если персонального нет — случайный из папки.

Музыку эти звуки не прерывают.
"""


def ensure_dirs() -> None:
    """Создаёт служебные каталоги (data/, data/sounds/) и инструкцию."""
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    readme = SOUNDS_DIR / "README.txt"
    if not readme.is_file():
        readme.write_text(SOUNDS_README, encoding="utf-8")

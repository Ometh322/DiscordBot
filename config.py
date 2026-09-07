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

# Громкость приветствий (множитель): 10 = сильно громче; усиление делается
# фильтром FFmpeg с лимитером — без жёсткого цифрового перегруза
WELCOME_VOLUME = min(30.0, max(0.1, float(os.getenv("WELCOME_VOLUME", "10.0"))))


SOUNDS_README = """\
Звуки приветствия (data/sounds)

Просто положи сюда аудиофайлы (mp3, ogg, wav, m4a, flac, opus) —
привязка к пользователям не нужна.

Когда участник заходит в голосовой канал (или вызывает /hello),
бот проигрывает СЛУЧАЙНЫЙ файл из этой папки.

Если в этот момент играла музыка — она приостановится, прозвучит
приветствие, и трек возобновится.

/hello — не чаще раза в 3 секунды; на вход в канал ограничений нет.
"""


def ensure_dirs() -> None:
    """Создаёт служебные каталоги (data/, data/sounds/) и инструкцию."""
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    readme = SOUNDS_DIR / "README.txt"
    if not readme.is_file():
        readme.write_text(SOUNDS_README, encoding="utf-8")

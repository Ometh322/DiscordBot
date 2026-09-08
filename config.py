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
Звуки (data/sounds)

Два типа по имени файла:
  welcome_<ник|id>.mp3      — личное приветствие: играет при входе
                              участника в голосовой канал; если файлов
                              несколько (welcome_ник_2, …) — случайный.
                              ник = логин или отображаемое имя в нижнем
                              регистре без пробелов, или ID пользователя.
  random<что угодно>.mp3    — «бормотание»: раз в минуту с шансом 20%
                              бот выдаёт случайный из них там, где сидит.

Файлы без префикса автоматически не играют — только через /hello.

/hello — своё приветствие (или случайный random…), кулдаун 3 с.
Если играла музыка — она приостанавливается и после звука
возобновляется с прежней позиции.
Загрузка: /sound вложением (до 10 МБ) или просто копированием сюда.
Форматы: mp3, ogg, wav, m4a, flac, opus.
"""


def ensure_dirs() -> None:
    """Создаёт служебные каталоги (data/, data/sounds/) и инструкцию."""
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    readme = SOUNDS_DIR / "README.txt"
    if not readme.is_file():
        readme.write_text(SOUNDS_README, encoding="utf-8")

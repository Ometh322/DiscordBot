"""Случайные гифки для сообщений о текущем треке (папка data/gifs).

Гифка прикрепляется к embed как вложение (attachment://…) и проигрывается
анимацией прямо в Discord. Пул общий — выбор случайный.
"""

import logging
import random
import re
from pathlib import Path
from typing import Optional

import discord

import config

log = logging.getLogger(__name__)

GIF_EXTENSIONS = (".gif", ".apng", ".png", ".jpg", ".jpeg", ".webp")
MAX_GIF_BYTES = 8 * 1024 * 1024   # 8 МБ на файл
MAX_GIF_FILES = 50                # предохранитель


def gif_files() -> list:
    folder = config.GIFS_DIR
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir() if p.suffix.lower() in GIF_EXTENSIONS
    )


def random_gif() -> Optional[Path]:
    files = gif_files()
    return random.choice(files) if files else None


def _url_safe_name(name: str) -> str:
    """attachment:// не дружит с пробелами/кириллицей — безопасное имя."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return cleaned or "gachi.gif"


def attach_random_gif(embed: discord.Embed) -> Optional[discord.File]:
    """Вставляет в embed случайную гифку.

    Возвращает discord.File — его нужно передать в send(file=...),
    иначе вложение не доедет и картинка не покажется.
    """
    path = random_gif()
    if path is None:
        return None
    safe = _url_safe_name(path.name)
    embed.set_image(url=f"attachment://{safe}")
    return discord.File(path, filename=safe)

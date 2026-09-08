"""Локальный каталог треков (SQLite): быстрая случайная выборка для /gachi.

Каталог наполняется результатами поисков (и прогревается при старте бота);
выборка идёт из базы за миллисекунды — сеть нужна только для свежей ссылки
на поток играющего трека (fresh_url). История проигрываний хранится
на сервер и переживает перезапуск.
"""

import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import List, Optional

import config
from services.soundcloud import Track

log = logging.getLogger(__name__)

RECENT_EXCLUDE_N = 60  # сколько последних треков сервера не повторять


class Catalog:
    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = str(db_path or config.DB_PATH)
        self._init_db()

    # ---- инфраструктура ----

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _run(self, fn):
        """Соединение закрывается всегда (with по con лишь коммитит)."""
        with closing(self._connect()) as con, con:
            return fn(con)

    def _init_db(self) -> None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._run(lambda con: con.executescript(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                track_id  TEXT PRIMARY KEY,
                title     TEXT NOT NULL DEFAULT '',
                artist    TEXT NOT NULL DEFAULT '',
                duration  INTEGER NOT NULL DEFAULT 0,
                page_url  TEXT NOT NULL DEFAULT '',
                lang      TEXT NOT NULL DEFAULT 'ang',
                added_at  REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS plays (
                guild_id  INTEGER NOT NULL,
                track_id  TEXT NOT NULL,
                played_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, track_id)
            );
            """
        ))

    # ---- API ----

    def upsert(self, tracks: List[Track], lang: str) -> int:
        """Добавляет треки в каталог (существующие не трогает)."""
        now = time.time()
        rows = [
            (t.track_id, t.title, t.artist, int(t.duration), t.page_url, lang, now)
            for t in tracks
            if t.track_id and t.page_url
        ]
        if not rows:
            return 0
        self._run(lambda con: con.executemany(
            "INSERT OR IGNORE INTO tracks "
            "(track_id, title, artist, duration, page_url, lang, added_at) "
            "VALUES (?,?,?,?,?,?,?)",
            rows,
        ))
        return len(rows)

    def count(self, lang: Optional[str] = None) -> int:
        q = "SELECT COUNT(*) FROM tracks"
        args: tuple = ()
        if lang:
            q += " WHERE lang=?"
            args = (lang,)
        return self._run(lambda con: con.execute(q, args).fetchone()[0])

    def recent_ids(self, guild_id: int) -> set:
        """ID последних проигранных треков сервера (для отсева повторов)."""
        rows = self._run(lambda con: con.execute(
            "SELECT track_id FROM plays WHERE guild_id=? "
            "ORDER BY played_at DESC LIMIT ?",
            (guild_id, RECENT_EXCLUDE_N),
        ).fetchall())
        return {r[0] for r in rows}

    def pick(self, lang: str, count: int, guild_id: Optional[int]) -> List[Track]:
        """Случайные треки языка lang, кроме последних проигранных на сервере."""
        exclude = self.recent_ids(guild_id) if guild_id is not None else set()
        if exclude:
            marks = ",".join("?" * len(exclude))
            rows = self._run(lambda con: con.execute(
                f"SELECT track_id,title,artist,duration,page_url FROM tracks "
                f"WHERE lang=? AND track_id NOT IN ({marks}) "
                f"ORDER BY RANDOM() LIMIT ?",
                (lang, *exclude, count),
            ).fetchall())
        else:
            rows = self._run(lambda con: con.execute(
                "SELECT track_id,title,artist,duration,page_url FROM tracks "
                "WHERE lang=? ORDER BY RANDOM() LIMIT ?",
                (lang, count),
            ).fetchall())
        return [
            Track(track_id=r[0], title=r[1], artist=r[2], duration=r[3], page_url=r[4])
            for r in rows
        ]

    def mark_played(self, guild_id: int, tracks: List[Track]) -> None:
        now = time.time()
        self._run(lambda con: con.executemany(
            "INSERT OR REPLACE INTO plays (guild_id, track_id, played_at) "
            "VALUES (?,?,?)",
            [(guild_id, t.track_id, now) for t in tracks if t.track_id],
        ))

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
            CREATE TABLE IF NOT EXISTS approvals (
                guild_id  INTEGER NOT NULL,
                track_id  TEXT NOT NULL,
                user_id   INTEGER NOT NULL,
                created_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, track_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS requests (
                guild_id     INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                track_id     TEXT NOT NULL,
                requested_at REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_requests_guild
                ON requests (guild_id, requested_at);
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

    # ---- гачирусы и одобрения ----

    def add_request(self, guild_id: int, user_id: int, tracks: List[Track]) -> None:
        """Кто заказал треки (для топа гачирусов)."""
        now = time.time()
        self._run(lambda con: con.executemany(
            "INSERT INTO requests (guild_id, user_id, track_id, requested_at) "
            "VALUES (?,?,?,?)",
            [(guild_id, user_id, t.track_id, now) for t in tracks if t.track_id],
        ))

    def approvals_add(self, guild_id: int, track_id: str, user_id: int) -> bool:
        """Одобрение ♂ (один раз на трек от пользователя). False — уже было."""
        cur = self._run(lambda con: con.execute(
            "INSERT OR IGNORE INTO approvals "
            "(guild_id, track_id, user_id, created_at) VALUES (?,?,?,?)",
            (guild_id, track_id, user_id, time.time()),
        ))
        return cur.rowcount > 0

    def top_requesters(self, guild_id: int, days: Optional[int] = None,
                       limit: int = 10) -> list:
        """[(user_id, count)] — кто заказал больше всех (days=None — за всё время)."""
        q = "SELECT user_id, COUNT(*) c FROM requests WHERE guild_id=?"
        args: list = [guild_id]
        if days:
            q += " AND requested_at > ?"
            args.append(time.time() - days * 86400)
        q += " GROUP BY user_id ORDER BY c DESC LIMIT ?"
        args.append(limit)
        return self._run(lambda con: con.execute(q, args).fetchall())

    def top_tracks(self, guild_id: int, limit: int = 10) -> list:
        """[(title, artist, count)] — топ треков по одобрениям ♂."""
        q = (
            "SELECT t.title, t.artist, COUNT(*) c FROM approvals a "
            "JOIN tracks t ON t.track_id = a.track_id "
            "WHERE a.guild_id=? GROUP BY a.track_id "
            "ORDER BY c DESC, t.title LIMIT ?"
        )
        return self._run(lambda con: con.execute(q, (guild_id, limit)).fetchall())

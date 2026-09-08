"""Слой SoundCloud: поиск треков (yt-dlp, scsearch) с фильтром GACHI/ГАЧИ
и свежие ссылки на аудиопоток перед проигрыванием.

Токены не нужны: yt-dlp работает с публичным веб-клиентом SoundCloud и
поддерживает его годами. Клиент синхронный — из asyncio вызывать через
asyncio.to_thread.
"""

import logging
import re
from dataclasses import dataclass
from typing import List

import yt_dlp

log = logging.getLogger(__name__)

GACHI_RE = re.compile(r"gachi|гачи|right version", re.IGNORECASE)

# Вариации запросов для случайной выборки по языку
SEARCH_QUERIES = {
    "ru": ["гачи", "гачи ремикс", "гачи микс", "гачи музыка", "гачи фонк"],
    "ang": [
        "gachi", "gachi remix", "gachimuchi", "gachi mix",
        "gachi mashup", "gachi phonk", "gachi bass boosted",
    ],
}

YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "socket_timeout": 20,
    "retries": 2,
}

# Плоский поиск: один API-запрос, без извлечения потоков для каждого трека
# (полное извлечение происходит только в fresh_url для играющего трека)
YDL_SEARCH_OPTS = {**YDL_OPTS, "extract_flat": "in_playlist"}


class SoundCloudError(Exception):
    """Базовая ошибка обращения к SoundCloud."""


class ScUnavailable(SoundCloudError):
    pass


class TrackUnavailable(SoundCloudError):
    pass


@dataclass
class Track:
    track_id: str
    title: str = ""
    artist: str = ""  # uploader
    duration: int = 0  # секунды
    page_url: str = ""

    @property
    def full_id(self) -> str:
        return str(self.track_id)

    @property
    def name(self) -> str:
        return f"{self.artist} — {self.title}".strip(" —")

    @classmethod
    def from_entry(cls, entry: dict) -> "Track":
        return cls(
            track_id=str(entry.get("id", "")),
            title=entry.get("title", "") or "Без названия",
            artist=entry.get("uploader", "") or entry.get("uploader_id", "") or "",
            duration=int(entry.get("duration") or 0),
            page_url=entry.get("webpage_url", "") or entry.get("url", ""),
        )


def is_gachi(track: Track) -> bool:
    return bool(GACHI_RE.search(f"{track.artist} {track.title}"))


def detect_lang(track: Track) -> str:
    """Язык трека для каталога: кириллическая гачи — ru, иначе ang."""
    return "ru" if "гачи" in f"{track.artist} {track.title}".lower() else "ang"


class SoundCloud:
    """Синхронный клиент. Каждый вызов создаёт свой YoutubeDL, поэтому
    параллельные вызовы из нескольких потоков безопасны (client_id
    кэшируется на уровне класса yt-dlp)."""

    def __init__(self):
        pass

    def search(
        self,
        query: str,
        count: int = 20,
        offset: int = 0,
        gachi_only: bool = True,
    ) -> List[Track]:
        """Ищет треки; при gachi_only оставляет только GACHI/ГАЧИ в названии.

        Плоский поиск — быстро (один запрос); потоки не извлекаются."""
        opts = dict(YDL_SEARCH_OPTS)
        opts["playlistend"] = offset + count
        if offset:
            opts["playliststart"] = offset + 1
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"scsearch{offset + count}:{query}", download=False
                )
        except yt_dlp.utils.DownloadError as e:
            log.warning("SoundCloud search '%s' -> %s", query, e)
            raise ScUnavailable(f"поиск недоступен ({str(e)[:120]})") from e

        entries = (info or {}).get("entries") or []
        tracks = [Track.from_entry(e) for e in entries if e]
        if gachi_only:
            tracks = [t for t in tracks if is_gachi(t)]
        return tracks

    def fresh_url(self, track: Track) -> str:
        """Свежая ссылка на аудиопоток (подписи SoundCloud протухают)."""
        if not track.page_url:
            raise TrackUnavailable(f"нет ссылки на трек ({track.name})")
        try:
            with yt_dlp.YoutubeDL({**YDL_OPTS, "format": "bestaudio/best"}) as ydl:
                info = ydl.extract_info(track.page_url, download=False)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "403" in msg or "404" in msg or "unavailable" in msg.lower():
                raise TrackUnavailable(f"трек недоступен ({track.name})") from e
            raise ScUnavailable(f"SoundCloud недоступен ({msg[:120]})") from e

        url = (info or {}).get("url")
        if not url:
            fmts = info.get("formats") or []
            http_audio = [
                f for f in fmts
                if f.get("protocol") in ("http", "https")
                and f.get("acodec") not in (None, "none")
            ]
            if http_audio:
                url = http_audio[0]["url"]
            elif fmts:
                url = fmts[-1]["url"]
        if not url:
            raise TrackUnavailable(f"нет аудиопотока у трека ({track.name})")
        return url

"""Слой SoundCloud: поиск треков (yt-dlp, scsearch) с фильтром GACHI/ГАЧИ
и свежие ссылки на аудиопоток перед проигрыванием.

Токены не нужны: yt-dlp работает с публичным веб-клиентом SoundCloud и
поддерживает его годами. Клиент синхронный — из asyncio вызывать через
asyncio.to_thread.
"""

import logging
import re
import threading
from dataclasses import dataclass
from typing import List

import yt_dlp

log = logging.getLogger(__name__)

GACHI_RE = re.compile(r"gachi|гачи", re.IGNORECASE)

YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "socket_timeout": 20,
    "retries": 2,
}


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


class SoundCloud:
    """Синхронный клиент; вызовы сериализуются локом."""

    def __init__(self):
        self._lock = threading.Lock()

    def search(
        self,
        query: str,
        count: int = 20,
        offset: int = 0,
        gachi_only: bool = True,
    ) -> List[Track]:
        """Ищет треки; при gachi_only оставляет только GACHI/ГАЧИ в названии."""
        opts = dict(YDL_OPTS)
        if offset:
            opts["playliststart"] = offset + 1
        opts["playlistend"] = offset + max(count, 5)  # scsearch отдаёт фиксированно
        try:
            with self._lock:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(f"scsearch{count}:{query}", download=False)
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
            with self._lock:
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

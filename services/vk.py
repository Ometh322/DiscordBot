"""Обёртка VK API: поиск аудио с фильтром GACHI/ГАЧИ и свежие mp3-ссылки.

Ссылки VK на mp3 живут ограниченное время, поэтому треки храним как
(owner_id, audio_id), а url получаем через audio.getById перед проигрыванием.

Клиент синхронный (vk_api на requests) — из asyncio вызывать через
asyncio.to_thread.
"""

import logging
import re
import threading
from dataclasses import dataclass
from typing import List, Optional

import requests
import vk_api

import config

log = logging.getLogger(__name__)

GACHI_RE = re.compile(r"gachi|гачи", re.IGNORECASE)
# Kate-токен работает только с UA клиента Kate Mobile и на «старых» версиях API
DEFAULT_KATE_UA = (
    "KateMobileAndroid/56 lite-460 "
    "(Android 4.4.2; SDK 19; x86; unknown Android SDK built for x86; en)"
)


class VkMusicError(Exception):
    """Базовая ошибка обращения к VK."""

class VkNotConfigured(VkMusicError):
    pass


class VkTokenInvalid(VkMusicError):
    pass


class VkApiUnavailable(VkMusicError):
    pass


class TrackUnavailable(VkMusicError):
    pass


@dataclass
class Track:
    owner_id: int
    audio_id: int
    artist: str = ""
    title: str = ""
    duration: int = 0

    @property
    def full_id(self) -> str:
        return f"{self.owner_id}_{self.audio_id}"

    @property
    def name(self) -> str:
        return f"{self.artist} — {self.title}".strip(" —")

    @property
    def vk_url(self) -> str:
        return f"https://vk.com/audio{self.full_id}"

    @classmethod
    def from_item(cls, item: dict) -> "Track":
        return cls(
            owner_id=item["owner_id"],
            audio_id=item["id"],
            artist=item.get("artist", ""),
            title=item.get("title", ""),
            duration=item.get("duration", 0),
        )


def is_gachi(track: Track) -> bool:
    return bool(GACHI_RE.search(f"{track.artist} {track.title}"))


class VkMusic:
    """Синхронный клиент VK; вызовы сериализуются локом (requests.Session
    не потокобезопасен)."""

    def __init__(self, token: Optional[str] = None):
        self._token = token or config.VK_TOKEN
        self._api = None
        self._call_lock = threading.Lock()

    def api(self):
        if self._api is None:
            if not self._token:
                raise VkNotConfigured(
                    "VK_TOKEN не задан в .env (получить: scripts\\get_vk_token.py)"
                )
            session = vk_api.VkApi(
                token=self._token, api_version=config.VK_API_VERSION
            )
            session.http.headers["User-agent"] = config.VK_USER_AGENT or DEFAULT_KATE_UA
            session.http.timeout = 15
            self._api = session.get_api()
        return self._api

    def search(
        self,
        query: str,
        count: int = 50,
        offset: int = 0,
        gachi_only: bool = True,
    ) -> List[Track]:
        """Ищет треки; при gachi_only оставляет только GACHI/ГАЧИ в названии."""
        raw = self._call("audio.search", q=query, count=count, offset=offset, sort=0)
        tracks = [Track.from_item(it) for it in raw.get("items", [])]
        if gachi_only:
            tracks = [t for t in tracks if is_gachi(t)]
        return tracks

    def fresh_url(self, track: Track) -> str:
        """Актуальная mp3-ссылка; кидает TrackUnavailable, если трек недоступен."""
        raw = self._call("audio.getById", audio_ids=track.full_id)
        items = raw.get("items", [])
        if not items:
            raise TrackUnavailable(f"трек удалён или скрыт ({track.name})")
        url = items[0].get("url")
        if not url:
            raise TrackUnavailable(f"трек закрыт правообладателем ({track.name})")
        return url

    def _call(self, method: str, **kwargs) -> dict:
        name, args = method, kwargs
        with self._call_lock:
            try:
                return getattr(self.api(), name)(**args)
            except vk_api.exceptions.AccessDenied as e:
                raise VkTokenInvalid(f"VK-токен недействителен ({e})") from e
            except vk_api.exceptions.AuthError as e:
                raise VkTokenInvalid(f"VK-токен отклонён ({e})") from e
            except vk_api.exceptions.ApiError as e:
                log.warning("VK API %s -> %s", name, e)
                raise VkApiUnavailable(f"VK API: {e}") from e
            except vk_api.exceptions.VkApiError as e:
                raise VkApiUnavailable(f"VK API: {e}") from e
            except requests.exceptions.RequestException as e:
                raise VkApiUnavailable(f"сеть/таймаут при обращении к VK ({e})") from e

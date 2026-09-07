"""Проверка VK_TOKEN из .env: жив ли токен и видит ли audio.search.

Запуск:
    venv\\Scripts\\python scripts\\check_vk.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vk_api

import config
from services.vk import DEFAULT_KATE_UA, VkMusic, VkMusicError


def main() -> None:
    if not config.VK_TOKEN:
        print("VK_TOKEN не задан в .env.")
        sys.exit(1)

    session = vk_api.VkApi(token=config.VK_TOKEN, api_version=config.VK_API_VERSION)
    session.http.headers["User-agent"] = config.VK_USER_AGENT or DEFAULT_KATE_UA
    vk = session.get_api()

    try:
        me = vk.users.get()[0]
    except vk_api.exceptions.VkApiError as e:
        print(f"Токен не работает (users.get): {e}")
        sys.exit(1)
    ua_kind = "Kate (из .env)" if config.VK_USER_AGENT else "Kate (по умолчанию)"
    print(f"Токен жив: id={me['id']} {me['first_name']} {me['last_name']}")
    print(f"User-Agent: {ua_kind}, версия API: {config.VK_API_VERSION}")

    try:
        vk_music = VkMusic()
        tracks = vk_music.search("gachi", count=30)
    except VkMusicError as e:
        print(f"audio.search недоступен: {e}")
        print("Перезапусти scripts\\get_vk_token.py — нужен Kate-токен.")
        sys.exit(1)

    print(f"audio.search работает: {len(tracks)} GACHI-треков прошли фильтр")
    for t in tracks[:5]:
        print(f"  - {t.name}  [{t.duration} c]")


if __name__ == "__main__":
    main()

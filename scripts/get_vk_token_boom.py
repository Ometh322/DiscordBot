"""Получение VK-токена для audio.* ручным способом — через приложение Boom.

Прямая парольная авторизация (Kate) упирается в Flood control, а браузерный
флоу проходит: логинимся на ВК в браузере и разрешаем доступ приложению
Boom (официальный музыкальный клиент ВК). Его токен видит audio.*,
запросы должны идти с User-Agent клиента Boom.

Что делает скрипт:
1. Открывает браузер на странице разрешения для Boom.
2. Ты входишь (лучше инкогнито, выделенный аккаунт ВК) и жмёшь «Разрешить».
3. Попадаешь на https://oauth.vk.com/blank.html#access_token=... —
   копируешь ВСЮ ссылку из адресной строки и вставляешь сюда.
4. Скрипт проверяет audio.search и audio.getById (свежая ссылка) и
   сохраняет VK_TOKEN / VK_USER_AGENT / VK_API_VERSION в .env.

Запуск:
    venv\\Scripts\\python scripts\\get_vk_token_boom.py
"""

import re
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from config import BASE_DIR

# Приложение Boom (официальный музыкальный клиент ВК) — константы из
# open-source библиотеки vk-audio-token
BOOM_APP_ID = "4705861"
BOOM_UA = (
    "VK_Music/4.2.1 "
    "(Android 5.1.1; SDK 22; x86_64; unknown Android SDK built for x86_64; en; 320x240)"
)

AUTH_URL = (
    "https://oauth.vk.com/authorize"
    f"?client_id={BOOM_APP_ID}"
    "&scope=audio,offline"
    "&redirect_uri=https://oauth.vk.com/blank.html"
    "&display=mobile"
    "&v=5.95"
    "&response_type=token"
)

API_VERSIONS_TO_TRY = ("5.95", "5.131", "5.220")


def extract_token(pasted: str):
    pasted = pasted.strip()
    if "#" in pasted:
        fragment = parse_qs(urlparse(pasted).fragment)
        if "access_token" in fragment:
            return (
                fragment["access_token"][0],
                fragment.get("user_id", ["?"])[0],
            )
    if re.fullmatch(r"[A-Za-z0-9_.\-]{20,}", pasted):
        return pasted, "?"
    raise ValueError(
        "Не нашёл access_token. Вставь всю ссылку из адресной строки после «Разрешить»."
    )


def api(method, token, version, **params):
    data = {"access_token": token, "v": version}
    data.update(params)
    r = requests.post(
        f"https://api.vk.ru/method/{method}",
        data=data,
        headers={"User-Agent": BOOM_UA},
        timeout=20,
    )
    return r.json()


def validate(token):
    """audio.search + audio.getById по нескольким версиям -> (ok, версия)."""
    for v in API_VERSIONS_TO_TRY:
        time.sleep(1)
        body = api("audio.search", token, v, q="gachi", count=20, sort=0)
        items = body.get("response", {}).get("items")
        if items is None:
            err = body.get("error", {})
            print(f"   search v={v}: [{err.get('error_code')}] {err.get('error_msg', '')[:60]}")
            continue
        with_url = [t for t in items if t.get("url")]
        print(f"   search v={v}: OK, треков {len(items)}, с mp3 {len(with_url)}")
        if not with_url:
            print("   …но mp3-ссылок нет — токен без аудио-прав, пробую дальше")
            continue
        # проверяем и getById — им пользуется плеер для свежих ссылок
        track_id = f"{with_url[0]['owner_id']}_{with_url[0]['id']}"
        body2 = api("audio.getById", token, v, audio_ids=track_id)
        ok2 = bool(body2.get("response", {}).get("items"))
        print(f"   getById v={v}: {'OK' if ok2 else 'НЕ работает'}")
        if ok2:
            return True, v
    return False, None


def whoami(token):
    body = api("users.get", token, "5.95")
    try:
        u = body["response"][0]
        return f"{u.get('first_name', '')} {u.get('last_name', '')} (id {u.get('id', '?')})"
    except Exception:
        return "?"


def save_to_env(values):
    env_path = BASE_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines()
    out, seen = [], set()
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else None
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in values.items():
        if key not in seen:
            out.append(f"{key}={val}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    print("Открываю браузер для авторизации ВК под приложением Boom…")
    print(f"Если не открылся — пройди по ссылке вручную:\n{AUTH_URL}\n")
    print("Войди под ВЫДЕЛЕННЫМ аккаунтом (лучше в режиме инкогнито),")
    print("на странице «Boom запрашивает доступ» нажми «Разрешить».\n")
    webbrowser.open(AUTH_URL)

    pasted = input("Вставь всю ссылку из адресной строки после «Разрешить»:\n> ")
    try:
        token, user_id = extract_token(pasted)
    except ValueError as e:
        print(str(e))
        sys.exit(1)
    print(f"\nТокен извлечён (user_id={user_id}). Проверяю audio-методы…")
    print(f"Аккаунт: {whoami(token)}")

    ok, version = validate(token)
    if not ok:
        print("\n❌ Токен Boom не видит audio.* — пришли вывод, придумаем другое")
        print("   (запасной вариант: эмулятор Android с приложением Kate/Boom).")
        sys.exit(1)

    save_to_env(
        {"VK_TOKEN": token, "VK_USER_AGENT": BOOM_UA, "VK_API_VERSION": version}
    )
    print(f"\n✅ Готово: VK_TOKEN + Boom UA + версия API {version} сохранены в .env")
    print("Теперь: venv\\Scripts\\python scripts\\test_music_core.py — живой тест.")


if __name__ == "__main__":
    main()

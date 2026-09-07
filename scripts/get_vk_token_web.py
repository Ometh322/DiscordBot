"""Получение VK-токена из браузерной сессии — БЕЗ парольного входа.

Почему так: парольный grant (oauth/token) ВК валилит Flood control'ом даже
для новых аккаунтов с новых IP. Обход — конвертация уже авторизованной
веб-сессии в токен приложения (схема vk_api._api_login):

    куки remixsid (+ p) -> oauth.vk.ru/authorize -> connect_internal
    -> auth.getOauthToken -> токен приложения с audio-правами.

Нужно от тебя: значение куки remixsid из браузера, где залогинен
ВЫДЕЛЕННЫЙ аккаунт ВК (см. инструкцию ниже). Пароль не спрашивает,
Flood control не задействует.

Запуск:
    venv\\Scripts\\python scripts\\get_vk_token_web.py

Как достать remixsid (Chrome/Edge):
    1. Открой vk.com залогиненным под нужным аккаунтом
    2. F12 -> вкладка «Application» (Приложение)
    3. Слева: Storage -> Cookies -> https://vk.com
    4. Найди строку remixsid (или remixsid6) -> скопируй Value
    5. (не обязательно) Куки -> https://login.vk.ru -> строка p -> Value

Кука — это твой доступ к аккаунту: она никуда не отправляется, кроме ВК,
и не сохраняется в файлы.
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

BASE_DIR = Path(__file__).resolve().parent.parent

# Приложение: официальный клиент ВК (его токены пока видят audio.*)
APP_ID = "2274003"
SCOPE = "audio,offline"

UA_BROWSER = "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0"
UA_ANDROID = "VKAndroidApp/4.13.1-1206 (Android 4.4.3; SDK 19; armeabi; ; ru)"

RE_LOCATION = re.compile(r'location\.href = "(.*?)"\+addr;')
RE_WINDOW_INIT = re.compile(r"window\.init = ({.*?});", re.DOTALL)

API_VERSIONS_TO_TRY = ("5.131", "5.95", "5.220")


def build_session(remixsid: str, p: str = None) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = UA_BROWSER
    s.cookies.set("remixsid", remixsid, domain=".vk.ru", path="/")
    s.cookies.set("remixsid", remixsid, domain=".vk.com", path="/")
    if p:
        s.cookies.set("p", p, domain=".login.vk.ru", path="/")
        s.cookies.set("p", p, domain=".id.vk.ru", path="/")
    return s


def exchange_cookies(s: requests.Session) -> dict:
    """Веб-сессия -> токен приложения (ветки по vk_api._api_login)."""
    r = s.get(
        "https://oauth.vk.ru/authorize",
        params={"client_id": APP_ID, "scope": SCOPE, "response_type": "token"},
        timeout=25,
    )
    print(f"   authorize -> HTTP {r.status_code}, final: {r.url[:80]}")

    if "act=blocked" in r.url:
        raise RuntimeError("Аккаунт заблокирован ВК.")

    # Ветка 1: токен сразу в адресе редиректа
    if "access_token" in r.url:
        url = r.url
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        if "authorize_url" in q:  # возможен двойной редирект
            inner = q["authorize_url"][0]
            if inner.startswith("https%3A"):
                inner = requests.utils.unquote(inner)
            url = inner
        frag = parse_qs(urlparse(url).fragment)
        if "access_token" in frag:
            return frag["access_token"][0]

    # Ветка 2: страница с location.href = "…"+addr;
    m = RE_LOCATION.search(r.text)
    if m:
        r2 = s.get(m.group(1), timeout=25)
        if "access_token" in r2.url:
            frag = parse_qs(urlparse(r2.url).fragment)
            if "access_token" in frag:
                return frag["access_token"][0]

    # Ветка 3: VK ID — обмен через connect_internal + auth.getOauthToken
    if "redirect_uri" in r.url:
        m = RE_WINDOW_INIT.search(r.text)
        if not m:
            raise RuntimeError(
                "Страница VK ID отдалась без window.init (ВК снова сменил разметку). "
                "Пришли мне первые 300 символов из вывода ниже."
            )
        auth_json = json.loads(m.group(1))
        return_auth_hash = auth_json["data"]["hash"]["return_auth"]

        r3 = s.post(
            "https://login.vk.ru/",
            params={"act": "connect_internal"},
            data={
                "uuid": "",
                "service_group": "",
                "return_auth_hash": return_auth_hash,
                "version": 1,
                "app_id": APP_ID,
            },
            headers={"Origin": "https://id.vk.ru"},
            timeout=25,
        )
        connect = r3.json()
        if connect.get("type") != "okay":
            raise RuntimeError(f"connect_internal: {str(connect)[:200]}")
        auth_token = connect["data"]["access_token"]
        auth_user_hash = connect["data"]["auth_user_hash"]

        r4 = requests.post(
            "https://api.vk.ru/method/auth.getOauthToken",
            data={
                "hash": return_auth_hash,
                "auth_user_hash": auth_user_hash,
                "app_id": APP_ID,
                "client_id": APP_ID,
                "scope": SCOPE,
                "access_token": auth_token,
                "is_seamless_auth": 1,
                "v": "5.207",
            },
            headers={"User-Agent": UA_ANDROID},
            timeout=25,
        )
        resp = r4.json().get("response")
        if isinstance(resp, dict):
            return resp.get("access_token")
        if isinstance(resp, str):
            return resp
        raise RuntimeError(f"getOauthToken: {r4.text[:200]}")

    # Похоже, сессию не приняли
    if "id.vk.ru" in r.url or "login" in r.url:
        raise RuntimeError(
            "Кука remixsid не принята (протухла или скопирована не полностью). "
            "Перелогинься в браузере и скопируй заново."
        )
    raise RuntimeError(f"Неизвестный ответ страницы: {r.url[:120]}")


def api(method, token, version, ua, **params):
    data = {"access_token": token, "v": version, "https": "1"}
    data.update(params)
    r = requests.post(
        f"https://api.vk.ru/method/{method}",
        data=data,
        headers={"User-Agent": ua},
        timeout=20,
    )
    return r.json()


def validate(token):
    """(ok, версия, рабочий UA) — пробуем Android и браузерный UA."""
    for ua_name, ua in (("Android-клиент", UA_ANDROID), ("браузерный", UA_BROWSER)):
        for v in API_VERSIONS_TO_TRY:
            time.sleep(1)
            body = api("audio.search", token, v, ua, q="gachi", count=20, sort=0)
            items = body.get("response", {}).get("items")
            if items is None:
                err = body.get("error", {})
                print(f"   [{ua_name}] v={v}: [{err.get('error_code')}] "
                      f"{err.get('error_msg', '')[:50]}")
                continue
            with_url = [t for t in items if t.get("url")]
            print(f"   [{ua_name}] v={v}: OK, треков {len(items)}, со ссылкой {len(with_url)}")
            if not with_url:
                continue
            track_id = f"{with_url[0]['owner_id']}_{with_url[0]['id']}"
            body2 = api("audio.getById", token, v, ua, audios=track_id)
            if body2.get("response"):
                print(f"   [{ua_name}] getById: OK")
                return True, v, ua
        print(f"   [{ua_name}] — аудио не подтверждено, пробую другой UA…")
    return False, None, None


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


def main() -> None:
    print(__doc__.split("\n\n")[0], "\n")
    remixsid = input("Вставь значение куки remixsid: ").strip()
    if not remixsid or len(remixsid) < 20:
        print("Похоже, это не remixsid — скопируй Value целиком из DevTools.")
        sys.exit(1)
    p = input("Кука p с login.vk.ru (Enter — пропустить): ").strip() or None

    s = build_session(remixsid, p)
    print("\nШаг 1: обмен веб-сессии на токен приложения…")
    try:
        token = exchange_cookies(s)
    except RuntimeError as e:
        print(f"   ❌ {e}")
        sys.exit(1)
    if not token:
        print("   ❌ Токен не получен")
        sys.exit(1)
    print("   Токен получен.")

    print("\nШаг 2: проверка audio.search / audio.getById…")
    ok, version, ua = validate(token)
    if not ok:
        print("\n❌ Токен есть, но аудио-методы не отвечают. Пришли полный вывод.")
        sys.exit(1)

    save_to_env(
        {"VK_TOKEN": token, "VK_USER_AGENT": ua, "VK_API_VERSION": version}
    )
    print(f"\n✅ Готово: VK_TOKEN + UA + API {version} сохранены в .env")
    print("Дальше: venv\\Scripts\\python scripts\\test_music_core.py")


if __name__ == "__main__":
    main()

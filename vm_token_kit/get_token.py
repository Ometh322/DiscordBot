"""Получение VK-токена с доступом к audio.* под ОФИЦИАЛЬНЫМ приложением ВК.

Автономная версия для запуска на машине с «чистым» IP (Ubuntu/Windows).

Контекст: в мае 2026 ВК закрыл аудио-методы для сторонних клиентов
(Kate/Boom). Рабочий путь — прямая авторизация grant_type=password под
официальным Android-клиентом ВК (app_id 2274003), как в vkpymusic.

Итог печатается и сохраняется в result.env — три строки (VK_TOKEN,
VK_USER_AGENT, VK_API_VERSION) для .env основного проекта.

Запуск:  python3 get_token.py
Прокси:  python3 get_token.py --proxy socks5://host:port
"""

import os
import re
import sys
import time
from getpass import getpass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

APP_ID = "2274003"
CLIENT_SECRET = "hHbZxrka2uZ6jB1inYsH"
USER_AGENT = "VKAndroidApp/4.13.1-1206 (Android 4.4.3; SDK 19; armeabi; ; ru)"

API_VERSIONS_TO_TRY = ("5.131", "5.95", "5.220")


def apply_proxy_from_args() -> None:
    if "--proxy" in sys.argv:
        i = sys.argv.index("--proxy")
        if i + 1 >= len(sys.argv):
            print("Укажи адрес прокси: --proxy socks5://host:port")
            sys.exit(1)
        proxy = sys.argv[i + 1]
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
        print(f"Иду через прокси: {proxy}")


def direct_grant(login, password, code=None, success_token=None):
    params = {
        "grant_type": "password",
        "client_id": APP_ID,
        "client_secret": CLIENT_SECRET,
        "username": login,
        "password": password,
        "scope": "audio,offline",
        "2fa_supported": "1",
        "force_sms": "1",
        "v": "5.131",
    }
    if code:
        params["code"] = code
    if success_token:
        params["success_token"] = success_token
    r = requests.post(
        "https://oauth.vk.com/token",
        data=params,
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    return r.json()


def request_sms(sid):
    requests.post(
        "https://api.vk.com/method/auth.validatePhone",
        data={"sid": str(sid), "v": "5.131"},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )


def extract_success_token(pasted: str) -> str:
    pasted = pasted.strip()
    if "success_token" in pasted:
        qs = urlparse(pasted)
        source = parse_qs(qs.fragment or qs.query)
        if "success_token" in source:
            return source["success_token"][0]
    if re.fullmatch(r"[A-Za-z0-9_\-]{10,}", pasted):
        return pasted
    raise ValueError("Не нашёл success_token — вставь ссылку после решения капчи.")


def api(method, token, version, **params):
    data = {"access_token": token, "v": version, "https": "1", "lang": "ru"}
    data.update(params)
    r = requests.post(
        f"https://api.vk.com/method/{method}",
        data=data,
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    return r.json()


def validate(token):
    for v in API_VERSIONS_TO_TRY:
        time.sleep(1)
        body = api("audio.search", token, v, q="gachi", count=20, sort=0)
        items = body.get("response", {}).get("items")
        if items is None:
            err = body.get("error", {})
            print(f"   search v={v}: [{err.get('error_code')}] {err.get('error_msg', '')[:60]}")
            continue
        with_url = [t for t in items if t.get("url")]
        print(f"   search v={v}: OK, треков {len(items)}, со ссылкой {len(with_url)}")
        if not with_url:
            continue
        track_id = f"{with_url[0]['owner_id']}_{with_url[0]['id']}"
        body2 = api("audio.getById", token, v, audios=track_id)
        ok2 = bool(body2.get("response"))
        print(f"   getById v={v}: {'OK' if ok2 else 'НЕ работает'}")
        if ok2:
            return True, v
    return False, None


def whoami(token):
    try:
        u = api("users.get", token, "5.131")["response"][0]
        return f"{u.get('first_name', '')} {u.get('last_name', '')} (id {u.get('id', '?')})"
    except Exception:
        return "?"


def save_result(token, version):
    path = Path(__file__).resolve().parent / "result.env"
    path.write_text(
        f"VK_TOKEN={token}\nVK_USER_AGENT={USER_AGENT}\nVK_API_VERSION={version}\n",
        encoding="utf-8",
    )
    return path


def main():
    apply_proxy_from_args()
    login = input("Логин ВК (телефон/email, лучше выделенного аккаунта): ")
    try:
        password = getpass("Пароль: ")
    except Exception:
        password = input("Пароль: ")

    print("\nШаг 1: прямая авторизация под официальным приложением ВК…")
    data = direct_grant(login, password)
    for _ in range(5):
        err = data.get("error")
        if err == "need_validation":
            print("   Нужен код подтверждения (2FA/SMS).")
            sid = data.get("validation_sid")
            if sid:
                print("   Запрашиваю SMS с кодом…")
                request_sms(sid)
            code = input("   Код из SMS/приложения: ").strip()
            data = direct_grant(login, password, code=code)
        elif err == "need_captcha":
            url = data.get("redirect_uri", "")
            print("   ВК требует капчу. Открой в браузере ссылку:")
            print(f"   {url}")
            print("   Реши капчу и вставь сюда итоговую ссылку (или success_token):")
            pasted = input("   > ")
            try:
                success = extract_success_token(pasted)
            except ValueError as e:
                print("  ", e)
                continue
            data = direct_grant(login, password, success_token=success)
        elif err == "invalid_request" and "code" in str(data.get("error_description", "")).lower():
            code = input("   Неверный код, попробуй ещё: ").strip()
            data = direct_grant(login, password, code=code)
        else:
            break

    token = data.get("access_token")
    if not token:
        err = str(data.get("error", ""))
        if "flood" in err.lower() or data.get("error_type") == "password_bruteforce_attempt":
            print("   Flood control и на этом IP — подожди ~24 ч или смени IP (--proxy).")
            sys.exit(1)
        desc = data.get("error_description") or err or data
        print(f"   Не получилось: {desc}")
        if err == "invalid_client":
            print("   (неверный логин или пароль)")
        sys.exit(1)
    print("   Токен получен.")

    print("\nШаг 2: проверка audio.search / audio.getById…")
    ok, version = validate(token)
    if not ok:
        print("\n❌ Токен не видит аудио-методы — пришли полный вывод скрипта.")
        sys.exit(1)

    path = save_result(token, version)
    print(f"\n✅ Готово! Аккаунт: {whoami(token)}")
    print("\nСкопируй эти три строки в .env основной машины:\n")
    print(f"VK_TOKEN={token}")
    print(f"VK_USER_AGENT={USER_AGENT}")
    print(f"VK_API_VERSION={version}")
    print(f"\n(они же сохранены в {path})")


if __name__ == "__main__":
    main()

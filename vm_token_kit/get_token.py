"""Получение Kate-токена ВК (доступ к методам audio.*) — автономная версия для ВМ.

Запускать с машины с «чистым» IP, если основной попал под Flood control:

    python3 get_token.py

Спрашивает логин/пароль интерактивно (лучше выделенный аккаунт ВК),
поддерживает 2FA. Результат печатается и сохраняется в result.env —
это три строки (VK_TOKEN, VK_USER_AGENT, VK_API_VERSION) для .env
основного проекта.

Опционально: --proxy socks5://host:port или http://host:port
"""

import os
import sys
import time
from getpass import getpass
from pathlib import Path

import requests

# Константы клиента Kate Mobile (публичные, из open-source vkaudiotoken)
KATE_APP_ID = "2685278"
KATE_SECRET = "lxhD8OD7dMsqtXIm5IUY"
KATE_UA = (
    "KateMobileAndroid/56 lite-460 "
    "(Android 4.4.2; SDK 19; x86; unknown Android SDK built for x86; en)"
)

API_VERSIONS_TO_TRY = ("5.220", "5.131", "5.95")


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


def direct_grant(login, password, code=None, captcha_sid=None, captcha_key=None):
    params = {
        "grant_type": "password",
        "client_id": KATE_APP_ID,
        "client_secret": KATE_SECRET,
        "username": login,
        "password": password,
        "scope": "audio,offline",
        "v": "5.131",
        "lang": "ru",
        "2fa_supported": "1",
    }
    if code:
        if code.upper() == "GET_CODE":
            params["force_sms"] = "1"
        else:
            params["code"] = code
    if captcha_sid:
        params["captcha_sid"] = captcha_sid
        params["captcha_key"] = captcha_key
    r = requests.get(
        "https://oauth.vk.ru/token",
        params=params,
        headers={"User-Agent": KATE_UA},
        timeout=20,
    )
    return r.json()


def validate(token):
    """Проверяет audio.search по нескольким версиям API -> (ok, версия, кол-во)."""
    for v in API_VERSIONS_TO_TRY:
        time.sleep(1)
        try:
            r = requests.post(
                "https://api.vk.ru/method/audio.search",
                data={
                    "access_token": token,
                    "v": v,
                    "q": "gachi",
                    "count": 20,
                    "sort": 0,
                },
                headers={"User-Agent": KATE_UA},
                timeout=20,
            )
            body = r.json()
        except requests.RequestException as e:
            print(f"   v={v}: сеть — {e}")
            continue
        items = body.get("response", {}).get("items")
        if items is not None:
            with_url = sum(1 for t in items if t.get("url"))
            print(f"   v={v}: OK, треков {len(items)}, с mp3-ссылкой {with_url}")
            return True, v, len(items)
        err = body.get("error", {})
        print(f"   v={v}: [{err.get('error_code')}] {err.get('error_msg', '')[:60]}")
    return False, None, 0


def whoami(token: str) -> str:
    try:
        r = requests.post(
            "https://api.vk.ru/method/users.get",
            data={"access_token": token, "v": "5.131"},
            headers={"User-Agent": KATE_UA},
            timeout=15,
        )
        u = r.json().get("response", [{}])[0]
        return f"{u.get('first_name', '')} {u.get('last_name', '')} (id {u.get('id', '?')})"
    except Exception:
        return "?"


def full_android_flow(login, password):
    """Полный путь vkaudiotoken: GCM-чекин -> receipt -> auth.refreshToken."""
    from vkaudiotoken import (
        AndroidCheckin,
        CommonParams,
        SmallProtobufHelper,
        TokenException,
        TokenReceiver,
    )

    params = CommonParams()
    pb = SmallProtobufHelper()
    print("   Чекин у Google как Android-устройства…")
    auth_data = AndroidCheckin(params, pb).do_checkin()

    receiver = TokenReceiver(login, password, auth_data, params, None)
    try:
        return receiver.get_token()
    except TokenException as e:
        if "need_validation" not in str(getattr(e, "data", "")) and "validation" not in str(e).lower():
            raise
        code = input("   Код 2FA (GET_CODE — прислать SMS): ").strip()
        receiver = TokenReceiver(login, password, auth_data, params, code)
        return receiver.get_token()


def save_result(token, version) -> Path:
    path = Path(__file__).resolve().parent / "result.env"
    path.write_text(
        f"VK_TOKEN={token}\nVK_USER_AGENT={KATE_UA}\nVK_API_VERSION={version}\n",
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

    print("\nШаг 1: прямая авторизация…")
    data = direct_grant(login, password)
    for _ in range(3):
        err = data.get("error")
        if err == "need_validation":
            print("   Нужен код подтверждения (2FA/SMS).")
            code = input("   Код (GET_CODE — прислать SMS): ").strip()
            data = direct_grant(login, password, code=code)
        elif err == "captcha_error":
            print("   Капча:", data.get("captcha_img", ""))
            captcha_key = input("   Введи текст с картинки: ").strip()
            data = direct_grant(
                login, password,
                captcha_sid=data.get("captcha_sid"), captcha_key=captcha_key,
            )
        else:
            break

    token = data.get("access_token")
    if not token:
        err = str(data.get("error", ""))
        if "flood" in err.lower() or data.get("error_type") == "password_bruteforce_attempt":
            print("   Flood control и на этом IP — ВМ уже отмечалась неудачными входами?")
            print("   Подожди ~24 ч или используй другой IP (--proxy …).")
            sys.exit(1)
        desc = data.get("error_description") or data.get("error") or data
        print(f"   Не получилось: {desc}")
        if "validate" in str(desc).lower() or "security" in str(desc).lower():
            print("   ВК требует подтвердить вход в браузере — пришли мне полный вывод.")
        sys.exit(1)
    print("   Токен получен.")

    print("\nШаг 2: проверка доступа к audio.search…")
    ok, version, _ = validate(token)

    if not ok:
        print("\nШаг 3: простой токен не видит audio.* — полный Android-флоу…")
        try:
            token = full_android_flow(login, password)
            print("   Токен обновлён.")
            ok, version, _ = validate(token)
        except Exception as e:
            print(f"   Полный флоу не удался: {e!r}")

    if not ok:
        print("\n❌ Доступ к audio.* не получен — пришли полный вывод скрипта.")
        sys.exit(1)

    save_result(token, version)
    print(f"\n✅ Готово! Аккаунт: {whoami(token)}")
    print("\nСкопируй эти три строки в .env основной машины (замени соответствующие):\n")
    print(f"VK_TOKEN={token}")
    print(f"VK_USER_AGENT={KATE_UA}")
    print(f"VK_API_VERSION={version}")
    print(f"\n(они же сохранены в файл {Path('result.env')})")


if __name__ == "__main__":
    main()

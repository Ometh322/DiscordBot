"""Получение VK_TOKEN с доступом к методам audio.* (токен Kate Mobile).

Токен из браузерного VK ID-флоу НЕ видит методы audio.* — ВК отдаёт их только
клиентам мобильных приложений. Рабочий способ — прямая авторизация
(grant_type=password) под клиентом Kate Mobile:

    1. Прямой запрос oauth.vk.ru/token (логин/пароль, +код 2FA при надобности).
    2. Проверка: видит ли токен audio.search.
    3. Если нет — полный прогон через библиотеку vkaudiotoken: «чекин» как
       Android-устройство у Google + auth.refreshToken (так делают живые
       VK-музыкальные боты).

Итог сохраняется в .env: VK_TOKEN, VK_USER_AGENT, VK_API_VERSION.

Запуск:
    venv\\Scripts\\python scripts\\get_vk_token.py

Через прокси (если VK отвечает «Flood control» — блокировка обычно на IP,
помогает другой IP: VPN/прокси или мобильный интернет):
    venv\\Scripts\\python scripts\\get_vk_token.py --proxy socks5://127.0.0.1:1080
    venv\\Scripts\\python scripts\\get_vk_token.py --proxy http://user:pass@host:port
"""

import os
import sys
import time
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from config import BASE_DIR

# Константы клиента Kate Mobile (публичные, из open-source vkaudiotoken)
KATE_APP_ID = "2685278"
KATE_SECRET = "lxhD8OD7dMsqtXIm5IUY"
KATE_UA = (
    "KateMobileAndroid/56 lite-460 "
    "(Android 4.4.2; SDK 19; x86; unknown Android SDK built for x86; en)"
)

API_VERSIONS_TO_TRY = ("5.220", "5.131", "5.95")


def apply_proxy_from_args() -> None:
    """--proxy URL -> переменные окружения: покрывает и внутренние сессии
    библиотеки vkaudiotoken (requests читает их автоматически)."""
    if "--proxy" in sys.argv:
        i = sys.argv.index("--proxy")
        if i + 1 >= len(sys.argv):
            print("Укажи адрес прокси: --proxy socks5://host:port")
            sys.exit(1)
        proxy = sys.argv[i + 1]
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
        print(f"Иду через прокси: {proxy}")


def read_password() -> str:
    try:
        return getpass("Пароль: ")
    except Exception:
        return input("Пароль (getpass недоступен — ввод будет виден): ")


def direct_grant(login: str, password: str, code: str = None,
                 captcha_sid: str = None, captcha_key: str = None) -> dict:
    """Прямая авторизация oauth.vk.ru/token без «чекина»."""
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


def validate(token: str):
    """Проверяет audio.search по нескольким версиям API.

    Возвращает (ok, рабочая_версия, количество_треков).
    """
    for v in API_VERSIONS_TO_TRY:
        time.sleep(1)  # щадим rate limit
        try:
            r = requests.post(
                f"https://api.vk.ru/method/audio.search",
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


def full_android_flow(login: str, password: str) -> str:
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


def save_to_env(values: dict) -> None:
    env_path = BASE_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines()
    out = []
    seen = set()
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
    apply_proxy_from_args()
    login = input("Логин ВК (телефон/email, лучше выделенного аккаунта): ")
    password = input("Введите пароль: ")

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
            print("   ВК временно заблокировал вход по паролю с этого IP (Flood control).")
            print("   Что делать:")
            print("   1) запустись через другой интернет — мобильный интернет, VPN или прокси:")
            print("      venv\\Scripts\\python scripts\\get_vk_token.py --proxy socks5://host:port")
            print("   2) либо подожди ~24 часа после последней попытки")
            print("      (каждая неудачная попытка продлевает блокировку — не спамь запусками).")
            sys.exit(1)
        desc = data.get("error_description") or data.get("error") or data
        print(f"   Не получилось: {desc}")
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
        print(
            "\n❌ Доступ к audio.* не получен. Пришли вывод этого скрипта — "
            "буду разбираться (ВК часто меняет правила игры)."
        )
        sys.exit(1)

    save_to_env(
        {"VK_TOKEN": token, "VK_USER_AGENT": KATE_UA, "VK_API_VERSION": version}
    )
    print(f"\n✅ Готово: VK_TOKEN + UA + версия API {version} сохранены в .env")


if __name__ == "__main__":
    main()

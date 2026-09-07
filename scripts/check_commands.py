"""Диагностика: какие глобальные слэш-команды зарегистрированы в Discord.

Запуск:
    venv\\Scripts\\python scripts\\check_commands.py
"""

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


def http_get(url: str, headers: dict):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        import json

        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    if not config.DISCORD_TOKEN:
        print("DISCORD_TOKEN не задан.")
        sys.exit(1)
    headers = {
        "Authorization": f"Bot {config.DISCORD_TOKEN}",
        "User-Agent": "DiscordBot (private diagnostic, 1.0)",
    }

    app = http_get("https://discord.com/api/v10/applications/@me", headers)
    app_id = app.get("id")
    print("Приложение:", app.get("name"), f"(id {app_id})")

    cmds = http_get(
        f"https://discord.com/api/v10/applications/{app_id}/commands", headers
    )
    if isinstance(cmds, dict):
        print("Ошибка API:", cmds)
        sys.exit(1)
    print(f"Зарегистрировано глобальных команд: {len(cmds)}")
    for c in sorted(cmds, key=lambda x: x["name"]):
        params = [p["name"] for p in c.get("options", [])]
        print(f"  /{c['name']} {params}")


if __name__ == "__main__":
    main()

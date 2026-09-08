# Развёртывание бота на ВМ (Ubuntu 22.04+)

В этой папке — всё для DevOps-развёртывания:

| Файл | Назначение |
|---|---|
| `install.sh` | Установка «в лоб»: системные пакеты + venv + `.env` |
| `discordbot.service` | Юнит systemd: автозапуск и авторестарты |
| `Dockerfile` | Образ бота (Python 3.12 + FFmpeg + зависимости) |
| `docker-compose.yml` | Запуск контейнера с пробросом `.env` и `data/` |
| `DEPLOY.md` | Этот файл |

## 0. Общее для всех способов

**Код и данные.** На ВМ нужен репозиторий (клонируется с
`https://github.com/Ometh322/DiscordBot.git`) и папка `data/` (создаётся сама).
Если на Windows-машине уже накоплены звуки приветствий и каталог треков —
перенеси папку `data/` целиком:

```bash
scp -r data/ user@VM:/opt/discordbot/
```

**`.env`** — единственный файл с секретами, в git не попадает. Минимум:

```ini
DISCORD_TOKEN=токен_бота_из_Developer_Portal
FFMPEG_PATH=ffmpeg        # на Linux ffmpeg ставится в PATH
# WELCOME_VOLUME=10       # громкость приветствий (множитель), опционально
```

**Требования к боту в Discord Developer Portal** (делается один раз,
независимо от машины): включены intents **Server Members** и **Voice States**
(первые — привилегированные, иначе бот не стартует).

---

## Способ 1. Простой (venv, без Docker)

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/Ometh322/DiscordBot.git /opt/discordbot
cd /opt/discordbot
nano .env            # вписать DISCORD_TOKEN
bash deploy/install.sh

# проверка — бот должен написать "bot online"
venv/bin/python bot.py
```

`install.sh` ставит `python3-venv`, `ffmpeg`, создаёт окружение из
`requirements.txt` и корректно выставляет `FFMPEG_PATH` в `.env`.

---

## Способ 2. Служба systemd (автозапуск и рестарты)

Рекомендуемый для постоянной работы: бот поднимется при старте ВМ и
перезапустится при падении.

```bash
# предполагается способ 1 в /opt/discordbot; правь User= и пути в юните при необходимости
sudo cp deploy/discordbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now discordbot
```

Управление и логи:

```bash
systemctl status discordbot       # состояние
journalctl -u discordbot -f       # живой лог (Ctrl+C — выйти)
journalctl -u discordbot --since "1 hour ago"
sudo systemctl restart discordbot # после изменений кода
sudo systemctl disable --now discordbot  # остановить и снять с автозапуска
```

---

## Способ 3. Docker

```bash
sudo apt update && sudo apt install -y git docker.io docker-compose-v2
git clone https://github.com/Ometh322/DiscordBot.git /opt/discordbot
cd /opt/discordbot
nano .env                      # DISCORD_TOKEN и т.п.

cd deploy
sudo docker compose up -d --build
sudo docker compose logs -f    # живой лог
```

Что делает `docker-compose.yml`:

- собирает образ по `deploy/Dockerfile` (внутри — Python 3.12-slim, FFmpeg,
  зависимости из `requirements.txt`);
- подхватывает переменные из корневого `.env`, перекрывая `FFMPEG_PATH=ffmpeg`
  (виндовый путь из локального `.env` внутри контейнера не работает);
- монтирует `../data` в контейнер — звуки приветствий и SQLite-каталог
  живут на хосте и переживают пересборку;
- `restart: unless-stopped` — автоподъём после падения и перезапуска ВМ.

> Если ваша версия Docker Compose не принимает `env_file: ../.env`
> (пути выше папки проекта), скопируй `.env` в `deploy/` и убери `../`.

Обновление на новую версию кода:

```bash
cd /opt/discordbot && git pull
cd deploy && sudo docker compose up -d --build
```

---

## Обновление бота (для способов 1–2)

```bash
cd /opt/discordbot
git pull
venv/bin/pip install -r requirements.txt   # если менялись зависимости
sudo systemctl restart discordbot          # для способа 2
```

## Частые вопросы

- **В логах `getaddrinfo failed` / переподключения** — кратковременно
  пропадала сеть/DNS на ВМ; бот сам переподключается, лечится стабильной
  сетью.
- **Бот не стартует с ошибкой PrivilegedIntentsRequired** — в Developer
  Portal не включён Server Members Intent (см. «Общее»).
- **Где данные?** Всё состояние — в `data/` (`sounds/`, `db.sqlite`).
  Бэкап = скопировать эту папку.
- **Windows-путь FFmpeg в `.env`** — на ВМ он не нужен: `install.sh`
  и `docker-compose.yml` сами ставят `FFMPEG_PATH=ffmpeg`.

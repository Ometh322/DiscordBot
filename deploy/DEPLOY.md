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
# WELCOME_VOLUME=10       # громкость приветствий (множитель), опционально
```

FFmpeg указывать не нужно: бинарь ставится через pip вместе с зависимостями
(пакет `imageio-ffmpeg`) — и на Linux, и на Windows. Если очень хочется
использовать системный — задай `FFMPEG_PATH=ffmpeg` (или полный путь).

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

`install.sh` ставит `python3-venv` и `git`, создаёт окружение из
`requirements.txt` — FFmpeg приезжает вместе с ними (пакет `imageio-ffmpeg`).

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

- собирает образ по `deploy/Dockerfile` (внутри — Python 3.12-slim и
  зависимости из `requirements.txt`, FFmpeg входит в них);
- подхватывает переменные из корневого `.env`;
- монтирует `../data` в контейнер — звуки, гифки и SQLite-каталог
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
- **Где данные?** Всё состояние — в `data/` (`sounds/`, `gifs/`, `db.sqlite`).
  Бэкап = скопировать эту папку.
- **FFmpeg** ставится через pip (`imageio-ffmpeg`) — ни `apt`, ни ручных путей
  не требуется; `FFMPEG_PATH` в `.env` нужен только для системного бинаря.

## Запуск из России (блокировка Discord, обход через zapret)

Discord блокируется на стороне провайдера; гейтвей-вебсокет через zapret
работает, но короткие REST-запросы (ответ на слэш-команду) обязаны укладываться
в **3 секунды** — агрессивные стратегии вроде `multidisorder` (дублирование
сегментов) задерживают их, и Discord отвечает
`404 Unknown interaction (10062)`.

Лечение: для доменов Discord — отдельная, «мягкая» стратегия без дублирования
пакетов. В `/opt/zapret/config` замените `NFQWS_OPT` на два блока —
первый (приоритетный) только для Discord, второй для всего остального:

```
NFQWS_OPT="
--filter-tcp=443 --dpi-desync=multisplit --dpi-desync-split-pos=2 --hostlist=/opt/zapret/ipset/zapret-hosts-discord.txt --new
--filter-tcp=443 --dpi-desync=multidisorder --dpi-desync-split-pos=2 --hostlist=/opt/zapret/ipset/zapret-hosts-user.txt --hostlist-exclude=/opt/zapret/ipset/zapret-hosts-discord.txt --new
"
```

И создайте файл списка доменов Discord:

```bash
cat >/opt/zapret/ipset/zapret-hosts-discord.txt <<'EOF'
discord.com
discord.gg
discordapp.com
discordapp.net
discord.media
EOF
```

Уберите эти домены из `zapret-hosts-user.txt` (если добавляли), затем
перезапустите обход:

```bash
systemctl restart zapret    # или /opt/zapret/init.d/sysv/zapret restart
```

Подбор стратегии: прогоните `/opt/zapret/blockcheck.sh` для `discord.com`
(и `discord.gg`), в списке работающих выбирайте варианты **без** `disorder`,
`dup`, `oob` — они дублируют/ломают сегменты и калечат короткие REST-запросы.
`multisplit`, `fake`, `split` — подходят. Итоговый вариант пропишите в
первый блок `NFQWS_OPT` выше.

Бот со своей стороны устойчив к редким «протухшим» interaction'ам:
команда выполнится (музыка заиграет), даже если красивый ответ не ушёл —
в логе будет строка `defer не прошёл … возраст interaction`. Если такие
строки сыпятся часто — стратегия для discord-доменов всё ещё тяжеловата,
поменяйте её через blockcheck.

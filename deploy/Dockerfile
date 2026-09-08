# Образ бота: Python 3.12 + зависимости из requirements.txt
# (FFmpeg ставится вместе с ними — пакет imageio-ffmpeg приносит бинарь)
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py config.py ./
COPY cogs/ cogs/
COPY services/ services/

# неотслеживаемые исходники запускаем сразу в stdout/err (docker logs)
CMD ["python", "-u", "bot.py"]

# Образ бота: Python 3.12 + системный FFmpeg + зависимости из requirements.txt
FROM python:3.12-slim

# Дебиановский FFmpeg: проверенная сборка; статический бинарь из
# imageio-ffmpeg в slim-контейнере падал по SIGSEGV (-11)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py config.py ./
COPY cogs/ cogs/
COPY services/ services/

# неотслеживаемые исходники запускаем сразу в stdout/err (docker logs)
CMD ["python", "-u", "bot.py"]

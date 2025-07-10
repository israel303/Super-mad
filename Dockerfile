FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TELEGRAM_TOKEN="" \
    BASE_URL="https://groky.onrender.com" \
    PORT=8443

RUN useradd -m -u 1000 appuser

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    libjpeg-dev \
    zlib1g-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN test -f thumbnail.jpg || { echo "thumbnail.jpg not found!"; exit 1; }
RUN test -f words_to_remove.txt || { echo "words_to_remove.txt not found!"; exit 1; }

RUN chown -R appuser:appuser /app

USER appuser

CMD ["python", "bot.py"]
# Используем официальный Python образ
FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    ca-certificates \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    libpng-dev \
    libjpeg-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    libtiff5-dev \
    libwebp-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Создаем директорию для временных файлов
RUN mkdir -p /tmp/app_temp && chmod 777 /tmp/app_temp

# Создаем пользователя приложения (безопасность)
RUN useradd -m -u 1000 racefinder && chown -R racefinder:racefinder /app /tmp/app_temp
USER racefinder

# Копируем requirements.txt и устанавливаем зависимости
COPY --chown=racefinder:racefinder run/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения из папки run/
COPY --chown=racefinder:racefinder run/ .

# Устанавливаем правильные права доступа к файлам
RUN chmod 644 config.json google-credentials.json 2>/dev/null || true && \
    chmod 755 *.py && \
    mkdir -p logs && \
    chown -R racefinder:racefinder /app

# Устанавливаем переменные окружения
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose порт (если нужен веб-интерфейс в будущем)
EXPOSE 8000

# Команда по умолчанию
CMD ["python", "main.py"]

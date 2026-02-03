# Sheets to WordPress Automation

Автоматизированная система для создания продуктов в WooCommerce на основе данных из Google Sheets с использованием OpenAI для генерации контента.

[![GitHub](https://img.shields.io/github/license/kodjooo/sheets-to-wp)](https://github.com/kodjooo/sheets-to-wp)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://github.com/kodjooo/sheets-to-wp)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT%20Integration-green)](https://github.com/kodjooo/sheets-to-wp)

## 🎯 Функционал

Система автоматически:
1. **Загружает данные** из Google Sheets (забеги, соревнования)
2. **Генерирует контент** с помощью OpenAI GPT (описания, преимущества, информация об организаторах)
3. **Создает изображения** с помощью DALL-E
4. **Переводит контент** на португальский язык
5. **Создает продукты** в WooCommerce с вариациями
6. **Настраивает атрибуты** и категории товаров
7. **Обновляет статус** в Google Sheets

## 🏗️ Архитектура

```
run/
├── main.py                    # Основной скрипт
├── _1_google_loader.py        # Загрузка данных из Google Sheets
├── _2_content_generation.py   # Генерация контента с OpenAI
├── _3_create_product.py       # Создание продуктов в WooCommerce
├── _4_create_translation.py  # Создание переводов
├── _5_taxonomy_and_attributes.py # Настройка атрибутов
├── _6_create_variations.py   # Создание вариаций товаров
├── .env                      # Переменные окружения (создается из env.template)
├── google-credentials.json   # Ключи Google API
└── requirements.txt         # Python зависимости
```

## 🚀 Быстрый старт

### 1. Клонирование репозитория

```bash
git clone https://github.com/kodjooo/sheets-to-wp.git
cd sheets-to-wp
```

### 2. Настройка окружения

```bash
# Создание файла переменных окружения
cp .env.example .env
nano .env  # Заполните реальными значениями
```

### 3. Настройка переменных окружения

Файл `.env` содержит **только реально используемые** переменные окружения:

```bash
# OpenAI API (обязательно)
OPENAI_API_KEY=sk-proj-ваш-ключ-openai
# Модели Responses API
OPENAI_TEXT_MODEL=gpt-4o-mini
OPENAI_SECOND_MODEL=gpt-4o-mini
# Уровень размышления (актуально для reasoning-моделей: low|medium|high)
OPENAI_TEXT_REASONING_EFFORT=
OPENAI_SECOND_REASONING_EFFORT=
# Температура генерации (0.0 - 2.0)
OPENAI_TEXT_TEMPERATURE=
OPENAI_SECOND_TEMPERATURE=
# Файлы системных промптов (путь относительно папки run или абсолютный путь)
OPENAI_SYSTEM_PROMPT_FILE=prompts/assistant_system.txt
OPENAI_SECOND_SYSTEM_PROMPT_FILE=prompts/second_system.txt

# OpenCage Geocoding API (обязательно)
OPENCAGE_API_KEY=ваш-opencage-ключ

# Google Sheets (обязательно)
GOOGLE_SPREADSHEET_ID=id-вашей-гугл-таблицы
GOOGLE_WORKSHEET_NAME=RACES

# WordPress/WooCommerce (обязательно)
WP_URL=https://ваш-сайт.com
WP_ADMIN_USER=admin-пользователь
WP_ADMIN_PASS=пароль-админа
WP_CONSUMER_KEY=ck_ваш-consumer-key
WP_CONSUMER_SECRET=cs_ваш-consumer-secret

# Настройки приложения (опционально)
SKIP_AI=false
SKIP_IMAGE=true
```

**Назначение переменных:**
- **Обязательные** - API ключи и настройки подключения к сервисам
- **Опциональные** - настройки поведения приложения (можно изменить в .env)

### 4. Настройка конфигурации

**Конфигурация:**
- Все настройки загружаются из переменных окружения в `.env` файле
- Скопируйте `.env.example` в `.env` и заполните реальными значениями
- Файл `config.json` больше не используется

```bash
# Пример .env файла
OPENAI_API_KEY=sk-proj-your-key-here
OPENAI_TEXT_MODEL=gpt-4o-mini
GOOGLE_SPREADSHEET_ID=your-spreadsheet-id-here
WP_URL=https://your-wordpress-site.com
# ... остальные переменные
```

### 5. Настройка Google API

Скопируйте файл сервисного аккаунта Google API в `run/google-credentials.json`.

Дополнительно поддерживаются переменные окружения:
- `GOOGLE_CREDENTIALS_FILE` — путь до файла сервисного аккаунта, если он хранится в другом месте;
- `GOOGLE_SERVICE_ACCOUNT_JSON` — JSON сервисного аккаунта целиком (удобно для секрет-хранилищ);
- `GOOGLE_SHEETS_CACHE_TTL_SEC`, `GOOGLE_SHEETS_UPDATE_MAX_ATTEMPTS`, `GOOGLE_SHEETS_UPDATE_BASE_DELAY_SEC` — тонкая настройка кеширования и повторных попыток при обращении к Google Sheets.
- `WCAPI_MAX_ATTEMPTS`, `WCAPI_BASE_DELAY_SEC` — управление повторными попытками при обращении к WooCommerce API.

## 🐳 Docker сборка и запуск

### Сборка образа

```bash
docker-compose build
```

### Запуск контейнера

```bash
# Запуск в фоновом режиме
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
```

### Управление контейнером

```bash
# Перезапуск
docker-compose restart

# Пересборка и перезапуск
docker-compose down && docker-compose build && docker-compose up -d

# Вход в контейнер для отладки
docker-compose exec racefinder bash

# Выполнение скрипта в контейнере
docker-compose exec racefinder python main.py
```

## 🌐 Развертывание на удаленном сервере

1. Установите Docker и docker-compose на сервере.
2. Клонируйте репозиторий и перейдите в папку проекта.
3. Создайте `.env` из `.env.example` и заполните значения.
4. Скопируйте сервисный аккаунт Google в `run/google-credentials.json`.
5. Запустите контейнеры:

```bash
docker-compose up -d --build
```

6. Проверьте логи и состояние:

```bash
docker-compose logs -f
docker-compose ps
```

## 📊 Мониторинг и логи

### Просмотр логов

```bash
# Все логи
docker-compose logs

# Логи в реальном времени
docker-compose logs -f

# Логи последних 100 строк
docker-compose logs --tail=100

# Логи приложения (если настроено логирование в файлы)
tail -f /var/log/racefinder-cron.log
```

Логи приложения записываются в контейнере в `/app/logs/automation.log`. В `docker-compose.yml` настроен volume, поэтому на сервере файл будет доступен по пути `/var/log/racefinder/automation.log`.

### Проверка статуса

```bash
# Статус контейнеров
docker-compose ps

# Использование ресурсов
docker stats
```

## ⏰ Автоматический запуск

### Настройка Cron

```bash
# Открыть crontab
crontab -e

# Добавить задачу (запуск каждый день в 9:00)
0 9 * * * cd /path/to/project && docker-compose up --build >> /var/log/racefinder-cron.log 2>&1
```

## 🔧 Устранение неполадок

### Частые проблемы

**Контейнер не запускается:**
```bash
# Проверить логи
docker-compose logs

# Проверить права доступа
ls -la .env run/google-credentials.json

# Пересобрать образ
docker-compose build --no-cache
```

**Ошибки API:**
- Проверить корректность API ключей в `.env`
- Убедиться в наличии интернет-соединения
- Проверить лимиты API запросов

**Проблемы с Google Sheets:**
- Проверить права доступа сервисного аккаунта
- Убедиться, что таблица доступна для сервисного аккаунта

**Ошибки WordPress:**
- Проверить доступность WordPress сайта
- Проверить корректность WooCommerce API ключей
- Убедиться в активации необходимых плагинов

## 📁 Структура проекта

```
sheets-to-wp/
├── README.md                 # Этот файл
├── docker-compose.yml        # Конфигурация Docker
├── Dockerfile               # Образ приложения
├── .env                     # Переменные окружения (создать из .env.example)
├── .env.example             # Пример переменных окружения
├── env.template             # Шаблон переменных окружения
└── run/                     # Код приложения
    ├── main.py
    ├── _1_google_loader.py
    ├── _2_content_generation.py
    ├── _3_create_product.py
    ├── _4_create_translation.py
    ├── _5_taxonomy_and_attributes.py
    ├── _6_create_variations.py
    ├── prompts/
    │   ├── assistant_system.txt
    │   ├── second_system.txt
    ├── .env
    ├── google-credentials.json
    └── requirements.txt
```

## 🛡️ Безопасность

### Права доступа

```bash
# Ограничить доступ к конфигурационным файлам
chmod 600 .env run/google-credentials.json
chown root:root .env run/google-credentials.json
```

### Файрвол

```bash
# Открыть только необходимые порты
sudo ufw allow ssh
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

## 🤝 Вклад в проект

1. Fork репозитория
2. Создайте feature branch (`git checkout -b feature/amazing-feature`)
3. Commit изменения (`git commit -m 'Add amazing feature'`)
4. Push в branch (`git push origin feature/amazing-feature`)
5. Откройте Pull Request

## 📄 Лицензия

Этот проект распространяется под лицензией MIT. См. файл `LICENSE` для подробностей.

## 📞 Поддержка

Если у вас возникли вопросы или проблемы:

1. Проверьте [Issues](https://github.com/kodjooo/sheets-to-wp/issues)
2. Создайте новый Issue с подробным описанием проблемы
3. Приложите логи и конфигурацию (без секретных данных)

---

**🎉 Готово! Ваш проект Sheets to WordPress Automation готов к работе.**

[GitHub Repository](https://github.com/kodjooo/sheets-to-wp) | [Issues](https://github.com/kodjooo/sheets-to-wp/issues) | [Documentation](https://github.com/kodjooo/sheets-to-wp#readme)

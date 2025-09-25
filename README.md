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
├── config.json               # Конфигурация приложения
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
cp env.template .env
nano .env  # Заполните реальными значениями
```

### 3. Настройка переменных окружения

Отредактируйте файл `.env`:

```bash
# OpenAI API
OPENAI_API_KEY=sk-proj-ваш-ключ-openai
ASSISTANT_ID_TEXT=asst_ваш-text-assistant-id
ASSISTANT_ID_PDF=asst_ваш-pdf-assistant-id

# OpenCage Geocoding API
OPENCAGE_API_KEY=ваш-opencage-ключ

# Google Sheets
GOOGLE_SPREADSHEET_ID=id-вашей-гугл-таблицы
GOOGLE_WORKSHEET_NAME=RACES

# WordPress/WooCommerce
WP_URL=https://ваш-сайт.com
WP_ADMIN_USER=admin-пользователь
WP_ADMIN_PASS=пароль-админа
WP_CONSUMER_KEY=ck_ваш-consumer-key
WP_CONSUMER_SECRET=cs_ваш-consumer-secret
```

### 4. Настройка конфигурации

Убедитесь, что файл `run/config.json` содержит актуальные данные:

```json
{
  "openai_api_key": "из .env",
  "assistant_id_text": "из .env",
  "assistant_id_pdf": "из .env",
  "opencage_api_key": "из .env",
  "spreadsheet_id": "из .env",
  "worksheet_name": "RACES",
  "sleep_seconds": 3,
  "wp_admin_user": "из .env",
  "wp_admin_pass": "из .env",
  "wp_url": "из .env",
  "consumer_key": "из .env",
  "consumer_secret": "из .env"
}
```

### 5. Настройка Google API

Скопируйте файл сервисного аккаунта Google API в `run/google-credentials.json`.

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
ls -la .env run/config.json run/google-credentials.json

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
├── .env                     # Переменные окружения (создать из env.template)
├── env.template             # Шаблон переменных окружения
└── run/                     # Код приложения
    ├── main.py
    ├── _1_google_loader.py
    ├── _2_content_generation.py
    ├── _3_create_product.py
    ├── _4_create_translation.py
    ├── _5_taxonomy_and_attributes.py
    ├── _6_create_variations.py
    ├── config.json
    ├── google-credentials.json
    └── requirements.txt
```

## 🛡️ Безопасность

### Права доступа

```bash
# Ограничить доступ к конфигурационным файлам
chmod 600 .env run/config.json run/google-credentials.json
chown root:root .env run/config.json run/google-credentials.json
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
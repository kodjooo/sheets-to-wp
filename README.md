# Sheets to WordPress Automation

Автоматизация публикации забегов из Google Sheets в WooCommerce с генерацией контента через OpenAI.

## Что делает сервис
- Читает строки из Google Sheets и обрабатывает статусы `Revised (incomplete)` и `Revised (complete)`.
- Для `Revised (incomplete)` генерирует и записывает AI-поля `ORG INFO/SUMMARY/BENEFITS/FAQ` (EN/PT), публикует карточку, сохраняет baseline hash `WEBSITE` и переводит строку в `Published (incomplete)`.
- Для `Published (incomplete)` ежедневно пересчитывает hash `WEBSITE` (с нормализацией HTML) и отправляет уведомление в Telegram при изменении.
- Для `Revised (complete)` генерирует EN/PT-контент через OpenAI и обновляет существующие EN/PT продукты в WP по сохранённым ID, а при отсутствии ID создаёт новые.
- Загружает данные из `WEBSITE` и `REGULATIONS` (HTML/PDF) с ретраями.
- Генерирует EN/PT-контент через OpenAI (основной и второй ассистент).
- Переводит `RACE NAME (PT)` в `RACE NAME` (PT→EN) через OpenAI.
- Создаёт variable-продукт в WooCommerce, категории, атрибуты и вариации.
- Создаёт PT-перевод через WPML API и синхронизирует ACF-поля.
- Записывает результаты и статус обратно в Google Sheets.

## Стек
- Python 3.11
- Docker / Docker Compose
- Google Sheets API (`gspread` + Service Account)
- OpenAI Responses API + Chat Completions (для перевода заголовка)
- WooCommerce REST API + JWT Auth + WPML custom API
- OpenCage Geocoding API
- Telegram (личный аккаунт через Telethon)

## Структура проекта
```text
.
├── README.md
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── env.template
├── docs/
│   ├── requirements.md
│   ├── architecture.md
│   ├── plan.md
│   └── arch-rules.md
├── run/
│   ├── main.py
│   ├── _1_google_loader.py
│   ├── _2_content_generation.py
│   ├── _3_create_product.py
│   ├── _4_create_translation.py
│   ├── _5_taxonomy_and_attributes.py
│   ├── _6_create_variations.py
│   ├── utils.py
│   ├── url_utils.py
│   ├── translation_prompt.py
│   ├── prompts/
│   │   ├── assistant_system.txt
│   │   └── second_system.txt
│   └── requirements.txt
└── tests/
```

## Настройка
1. Скопируйте пример переменных:
```bash
cp .env.example .env
```
2. Заполните `.env` реальными секретами.
3. Подготовьте Google credentials:
- либо файл `run/google-credentials.json`;
- либо переменную `GOOGLE_SERVICE_ACCOUNT_JSON`.
4. Для Telegram через Telethon выполните одноразовую авторизацию сессии:
```bash
docker compose run --rm -it racefinder python init_telethon_session.py
```

Важно: `.env` не должен попадать в Git.

## Запуск в Docker
```bash
docker compose up -d --build
docker compose logs -f
```

Остановка:
```bash
docker compose down
```

## Развертывание на удалённом сервере
1. Установите Docker и Docker Compose.
2. Клонируйте репозиторий:
```bash
git clone https://github.com/kodjooo/sheets-to-wp.git
cd sheets-to-wp
```
3. Создайте `.env` из `.env.example` и заполните значения.
4. Разместите `run/google-credentials.json` (или задайте `GOOGLE_SERVICE_ACCOUNT_JSON`).
5. Запустите сервис:
```bash
docker compose up -d --build
```
6. Проверьте состояние:
```bash
docker compose ps
docker compose logs -f
```

## Основные переменные окружения
Полный список — в `.env.example` и `env.template`.

Критично обязательные:
- `OPENAI_API_KEY`
- `OPENCAGE_API_KEY`
- `GOOGLE_SPREADSHEET_ID`
- `WP_URL`
- `WP_ADMIN_USER`
- `WP_ADMIN_PASS`
- `WP_CONSUMER_KEY`
- `WP_CONSUMER_SECRET`

Операционные:
- `PT_RETRY_ATTEMPTS`
- `TELEGRAM_NOTIFICATIONS_ENABLED`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION_NAME`
- `TELEGRAM_TARGET`
- `HTTP_FETCH_RETRY_DELAYS_SEC`
- `HTTP_FETCH_INSECURE_HOSTS`
- `WCAPI_MAX_ATTEMPTS`
- `WCAPI_BASE_DELAY_SEC`
- `WCAPI_TIMEOUT_SEC`
- `LOG_LEVEL`
- `LOG_FILE`

## Логи
- stdout контейнера: `docker compose logs -f`
- файл в контейнере: `/app/logs/automation.log`
- на хосте (по `docker-compose.yml`): `/var/log/racefinder/automation.log`

## Тесты
Запуск из контейнера:
```bash
docker compose run --rm racefinder sh -lc "cd /app && python -m pytest -q"
```

## Репозиторий
- GitHub: [https://github.com/kodjooo/sheets-to-wp](https://github.com/kodjooo/sheets-to-wp)

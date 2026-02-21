# Архитектура сервиса

## Обзор
Сервис — однопроцессный Python-воркер в Docker. Он читает строки Google Sheets, обрабатывает только строки со статусом `revised`, генерирует контент через OpenAI, публикует EN/PT товары в WooCommerce и записывает результаты обратно в таблицу.

## Компоненты
- `run/main.py` — оркестрация пайплайна, планировщик, обновление статусов, логирование.
- `run/_1_google_loader.py` — чтение/обновление Google Sheets, кеш worksheet, ретраи, загрузка конфигурации из `.env`.
- `run/_2_content_generation.py` — загрузка и валидация источников (WEBSITE/REGULATIONS), OpenAI-вызовы, перевод заголовка, геокодинг, генерация изображения.
- `run/_3_create_product.py` — создание EN-продукта, категорий, ACF-полей, JWT для ACF.
- `run/_4_create_translation.py` — создание PT-продукта, связка перевода с EN через WPML API, ACF PT.
- `run/_5_taxonomy_and_attributes.py` — создание/поиск атрибутов и термов, назначение атрибутов продукту.
- `run/_6_create_variations.py` — создание вариаций с проверкой дубликатов и retry-запросами.
- `run/utils.py` — нормализация атрибутов/категорий, проверка неполных PT-полей, FAQ parser.
- `run/prompts/*.txt` — системные промпты для первого и второго ассистента.

## Поток обработки
1. Чтение всех строк Google Sheets.
2. Фильтрация строк со статусом `revised`.
3. Геокодинг (`LOCATION`, затем fallback на `LOCATION (CITY)`).
4. Загрузка источников:
- `WEBSITE` (HTML-текст),
- `REGULATIONS` (HTML-текст или PDF как файл для OpenAI).
5. Проверка валидности источников; при ошибке — запись `STATUS=Error: ...` и пропуск строки.
6. Генерация контента первым ассистентом (Responses API).
7. Пост-обработка вторым ассистентом (очистка блоков, проверка структуры).
8. Проверка пар EN/PT (`summary`, `org_info`, `benefits`, `faq`) и дополнительные повторы второго ассистента по `PT_RETRY_ATTEMPTS`.
9. Создание EN-продукта (draft), категорий, ACF.
10. Назначение атрибутов и создание вариаций EN.
11. Создание PT-перевода, связка WPML, ACF PT, атрибуты и вариации PT.
12. Обновление полей и статуса строки в Google Sheets.

## Интеграции
- Google Sheets API (`gspread`, service account).
- OpenAI:
- Responses API для основной генерации,
- Chat Completions для перевода названия (`translate_title_to_en`).
- OpenCage Geocoding API.
- WooCommerce REST API.
- WordPress JWT Auth (`/wp-json/jwt-auth/v1/token`).
- ACF REST API (`/wp-json/acf/v3/product/{id}`).
- WPML custom API (`/wp-json/custom-api/v1/set-translation/`).

## Конфигурация
Все настройки задаются через `.env`.

Ключевые группы:
- OpenAI: модели, reasoning effort, temperature, пути к промптам.
- Google: spreadsheet, worksheet, credentials file/json, кеш и ретраи обновлений.
- WordPress/WooCommerce: URL, admin user/pass, consumer key/secret.
- HTTP fetch: user-agent, retry delays, whitelist хостов без SSL-проверки.
- Retry и таймауты WooCommerce: `WCAPI_*`.
- Планировщик: `RUN_ON_STARTUP`, `SCHEDULED_HOUR`, `SCHEDULED_MINUTE`, `TIMEZONE`.
- Логи: `LOG_LEVEL`, `LOG_FILE`.

## Надёжность и защита от сбоев
- Ретраи для Google Sheets чтения и обновления.
- Ретраи загрузки WEBSITE/REGULATIONS с настраиваемыми задержками.
- Ретраи WooCommerce API с экспоненциальной задержкой.
- Нормализация URL без схемы (`https://...`).
- Опциональное точечное отключение SSL-проверки для проблемных хостов через `HTTP_FETCH_INSECURE_HOSTS`.
- Нормализация атрибутов и вариаций для защиты от дублей из-за пробелов.
- Явная ошибка при неоднозначном совпадении WooCommerce-атрибутов по slug/name.

## Docker и запуск
- Сервис запускается через `docker-compose.yml`.
- Код монтируется в `/app/run` в режиме read-only.
- Google credentials монтируются в `/app/google-credentials.json`.
- Логи сохраняются на хост в `/var/log/racefinder`.
- В образе обновляются CA-сертификаты, выставлены `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`.

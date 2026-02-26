# Архитектура сервиса

## Обзор
Сервис — однопроцессный Python-воркер в Docker. Он читает строки Google Sheets, обрабатывает статусы `Revised (incomplete)` и `Revised (complete)`, публикует/обновляет EN/PT товары в WooCommerce, хранит baseline hash `WEBSITE`, мониторит изменения страниц и отправляет уведомления в Telegram.

## Компоненты
- `run/main.py` — оркестрация пайплайна, планировщик, обновление статусов, логирование.
- `run/_1_google_loader.py` — чтение/обновление Google Sheets, кеш worksheet, ретраи, загрузка конфигурации из `.env`.
- `run/_2_content_generation.py` — загрузка и валидация источников (WEBSITE/REGULATIONS), OpenAI-вызовы, перевод заголовка, геокодинг, генерация изображения.
- `run/_3_create_product.py` — создание/обновление EN-продукта, категорий, ACF-полей, JWT для ACF.
- `run/_4_create_translation.py` — создание/обновление PT-продукта, связка перевода с EN через WPML API, ACF PT.
- `run/_5_taxonomy_and_attributes.py` — создание/поиск атрибутов и термов, назначение атрибутов продукту.
- `run/_6_create_variations.py` — синхронизация вариаций (create/update/delete) с retry-запросами.
- `run/utils.py` — нормализация атрибутов/категорий, проверка неполных PT-полей, FAQ parser.
- `run/website_snapshot.py` — расчёт/сравнение hash `WEBSITE` с нормализацией HTML и Telegram-уведомления.
- `run/prompts/*.txt` — системные промпты для первого и второго ассистента.

## Поток обработки
1. Чтение всех строк Google Sheets.
2. Маршрутизация по статусам:
- `Revised (incomplete)` — генерация AI-контента + публикация + baseline hash,
- `Revised (complete)` — генерация контента + публикация/обновление,
- `Published (incomplete)` — мониторинг WEBSITE и уведомления.
3. Для `Revised (complete)`: геокодинг (`LOCATION`, fallback на `LOCATION (CITY)`).
4. Для `Revised (complete)`: загрузка источников:
- `WEBSITE` (HTML-текст),
- `REGULATIONS` (HTML-текст или PDF как файл для OpenAI).
5. Проверка валидности источников; при ошибке — запись `STATUS=Error: ...` и пропуск строки.
6. Генерация контента первым ассистентом (Responses API).
7. Пост-обработка вторым ассистентом (очистка блоков, проверка структуры).
8. Проверка пар EN/PT (`summary`, `org_info`, `benefits`, `faq`) и дополнительные повторы второго ассистента по `PT_RETRY_ATTEMPTS`.
9. Создание или обновление EN-продукта (draft), категорий, ACF.
10. Назначение атрибутов EN и синхронизация вариаций EN по `WP VARIATION ID EN`:
- обновление существующих,
- создание новых,
- удаление отсутствующих в таблице.
11. Создание или обновление PT-перевода, связка WPML, ACF PT, атрибуты PT.
12. Синхронизация вариаций PT по `WP VARIATION ID PT` (update/create/delete).
13. Для `Revised (incomplete)` генерируются и записываются поля `ORG INFO/SUMMARY/BENEFITS/FAQ` (EN/PT), затем рассчитывается baseline hash `WEBSITE`.
14. Для `Published (incomplete)` рассчитывается текущий hash `WEBSITE`; при изменениях отправляется Telegram.
15. Обновление полей и статуса строки в Google Sheets, включая `WP VARIATION ID EN/PT` для каждой строки вариации.

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
- Telegram через Telethon (личный аккаунт) для уведомлений о diff.

## Конфигурация
Все настройки задаются через `.env`.

Ключевые группы:
- OpenAI: модели, reasoning effort, temperature, пути к промптам.
- Google: spreadsheet, worksheet, credentials file/json, кеш и ретраи обновлений.
- WordPress/WooCommerce: URL, admin user/pass, consumer key/secret.
- HTTP fetch: user-agent, retry delays, whitelist хостов без SSL-проверки.
- Telegram: `TELEGRAM_NOTIFICATIONS_ENABLED`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_NAME`, `TELEGRAM_TARGET`.
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
- Синхронизация вариаций по ID: фактическое состояние вариаций в WooCommerce приводится к состоянию таблицы.
- Явная ошибка при неоднозначном совпадении WooCommerce-атрибутов по slug/name.
- Частичное обновление EN/PT продукта: пустые значения из таблицы не затирают существующие поля в WordPress.

## Docker и запуск
- Сервис запускается через `docker-compose.yml`.
- Код монтируется в `/app/run` в режиме read-only.
- Google credentials монтируются в `/app/google-credentials.json`.
- Логи сохраняются на хост в `/var/log/racefinder`.
- В образе обновляются CA-сертификаты, выставлены `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`.

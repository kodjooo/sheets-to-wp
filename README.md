# Sheets to WordPress Automation

Автоматизация публикации забегов из Google Sheets в WooCommerce с генерацией контента через OpenAI.

## Что делает сервис
- Для новых мероприятий поддерживает PT+ES+EN; существующие строки сохраняют прежний режим (подготовка описана ниже).
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
- Отдельным ручным скриптом восстанавливает старые `WP PRODUCT ID EN/PT` и `WP VARIATION ID EN/PT`, если карточки уже опубликованы, а ID не были сохранены в таблице.

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

## Recovery старых WP ID
Скрипт `run/recover_wp_ids.py` не запускается ежедневным pipeline. Он нужен для ранее опубликованных карточек, где в Google Sheets пусты `WP PRODUCT ID EN`, `WP PRODUCT ID PT`, `WP VARIATION ID EN` или `WP VARIATION ID PT`.

Dry-run без записи в таблицу:
```bash
docker compose run --rm racefinder python recover_wp_ids.py --mode dry-run
```

Apply с точечной записью только пустых ID:
```bash
docker compose run --rm racefinder python recover_wp_ids.py --mode apply
```

Ограничить количество основных строк:
```bash
docker compose run --rm racefinder python recover_wp_ids.py --mode dry-run --limit 10
```

Записать CSV-отчет:
```bash
docker compose run --rm racefinder python recover_wp_ids.py --mode dry-run --report /app/logs/recovery_wp_ids.csv
```

Скрипт сначала ищет product ID из `LINK RACEFINDER`, затем PT-перевод через публичную страницу и `hreflang="pt-pt"`. Если прямые источники недоступны, он ищет товар по ACF `event_ticket_url`, затем по составному ключу: название, дата старта, город и категории. Вариации EN/PT загружаются через Store API с fallback на WooCommerce REST API и сопоставляются по нормализованному ключу атрибутов (`TYPE`, `DISTANCE`, `TEAM`, `LICENSE`, дата и время старта), а не по названию. Неоднозначные совпадения логируются и не записываются автоматически.

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
- `RECOVERY_WP_IDS_MODE`
- `RECOVERY_WP_IDS_LIMIT`
- `RECOVERY_WP_IDS_PRODUCT_SCAN_PAGES`
- `RECOVERY_WP_IDS_REPORT`
- `WCAPI_MAX_ATTEMPTS`
- `WCAPI_BASE_DELAY_SEC`
- `WCAPI_TIMEOUT_SEC`
- `LOG_LEVEL`
- `LOG_FILE`

## Логи
- stdout контейнера: `docker compose logs -f`
- файл в контейнере: `/app/logs/automation.log`
- на хосте (по `docker-compose.yml`): `/var/log/racefinder/automation.log`

## Backfill контактов организаторов

`backfill_organizer_contacts.py` — отдельная ручная команда для исторических
мероприятий без `ORGANIZER EMAIL`. Она читает сайт и регламент, вызывает AI
только для извлечения организатора и подтверждённого email и не запускает
генерацию контента, изображений или обновление WordPress.

Модель и reasoning для этой команды независимы от ежедневного pipeline:
`OPENAI_CONTACTS_MODEL=gpt-6.1-sol` и
`OPENAI_CONTACTS_REASONING_EFFORT=low`.

Сначала всегда запускается проверка без записи:

```bash
docker compose run --rm racefinder python backfill_organizer_contacts.py --mode dry-run --limit 20 --report /app/logs/organizer_contacts_dry_run.csv
```

После ручной проверки CSV-отчёта можно применить результат. Скрипт пишет только
пустые `ORGANIZER EMAIL` и `ORGANIZER NAME`, повторно проверяя ячейку прямо перед
записью, поэтому существующие и добавленные вручную значения не перезаписываются:

```bash
docker compose run --rm racefinder python backfill_organizer_contacts.py --mode apply --report /app/logs/organizer_contacts_apply.csv
```

Для проверки одного мероприятия используйте повторяемый параметр `--id`.

## Тесты
Запуск из контейнера:
```bash
docker compose run --rm racefinder sh -lc "cd /app && python -m pytest -q"
```

## Репозиторий
- GitHub: [https://github.com/kodjooo/sheets-to-wp](https://github.com/kodjooo/sheets-to-wp)

## Испания: исходный режим импорта ES/EN (LEGACY)

Общая вкладка поддерживает `COUNTRY`: `Portugal`/`PT` и `Spain`/`ES`/`España`.
Старое пустое значение сохраняет поведение Португалии; неизвестная страна отклоняется.
Для Испании добавьте `RACE NAME (ES)`, `SUMMARY (ES)`, `ORG INFO (ES)`, `BENEFITS (ES)`,
`FAQ (ES)`, `WP PRODUCT ID ES`, `WP VARIATION ID ES`; английские колонки общие.
В режиме LEGACY поля PT в испанских строках не читаются и не перезаписываются. Внутри старого
пайплайна используется адаптер совместимости ключей, языковые значения — ES/EN.
`BOOK URL` при наличии используется для внешней регистрации, иначе `WEBSITE`.

География использует контракт rf-auto-location из ветки Кирилла `kt/53-two-domains`:
`_rf_location_country=es`, `_rf_location_municipality_name`, `_rf_location_province_name`.
Муниципалитет берётся из `MUNICIPALITY` либо `LOCATION (CITY)` (город, провинция),
провинция — из `PROVINCE` или второй части города. Справочник ES из той же ветки
хранится в `rf_es_geography.json`; неизвестные/неоднозначные места отклоняются.
Перед импортом на DEV должен быть установлен новый мост и зарегистрированы ES-таксономии.
До записи нужны `es_parent_id`/`en_parent_id` в `CATEGORY_ROOT_MAP_JSON`, совпадение `SPAIN_WP_HOST`
с хостом `WP_URL` и явный `ENABLE_SPAIN=true`. По умолчанию Испания выключена.
Не используйте ID товаров и категорий PROD для DEV: ID принадлежат конкретной базе WP.
Обе языковые версии получают страну/географию и связь ES -> EN; новые карточки — draft.
Первичная проверка с фиксированными текстами описана в docs/dev-import-validation-20261029.json.
Полный прогон 29.10.2026 выполнен на существующем DEV с временным переключением ветки:
настоящие Google Sheets, источники и OpenAI, два ES+EN мероприятия и одно PT+EN.
Проверены цены/дистанции, география, Book, шесть страниц и стабильные ID при повторе
и явном обновлении. Отчёт: docs/dev-live-validation-20261029.json.
Исходная ветка DEV восстановлена, временные товары и доступы удалены.
Источники Running.life
и RockTheSport согласованы; адаптеры находятся в репозитории монитора.

Проверка экспортированных CSV/JSON без API, ключей и записи в таблицу/WordPress:
`python run/preview_country_import.py --input events.csv --report preview.json --wp-url https://dev.racefinder.pt`.
Команду выполняйте в Docker с примонтированными входным файлом и каталогом отчёта.
Проверка показывает готовность колонок и конфигурации, но не генерирует контент и
не подтверждает работоспособность API/таксономий DEV. Для 20–30 реальных карточек
сначала подготовьте строки и проверьте отчёт; затем запускайте публикацию только на DEV.

Изолированный Compose-сервис `racefinder-dev` включается только профилем `dev`.
Скопируйте `.env.dev.example` в `.env.dev`, положите экспорт в `dev-input/events.csv`,
затем выполните `docker compose --profile dev run --rm racefinder-dev` — по умолчанию
это только preview. Рабочий `.env` этому сервису не передаётся, WordPress-хост
зафиксирован на DEV. Для реального обращения к таблице задайте ID её тестовой копии
через `RF_DEV_SPREADSHEET_ID`; без него импорт не запустится. Реальную публикацию
проводите только после установки ES-ветки и проверки DEV-доступов.

Общая вкладка `RACES` остаётся источником данных для обеих стран. `PROCESS_COUNTRY=all`
сохраняет общий проход; `pt`/`es` ограничивают и публикацию, и мониторинг изменений
`Published (incomplete)` своей страной. Не запускайте общий и отдельные проходы
одновременно: они записывают одни и те же строки. Для независимого расписания
используйте последовательные одноразовые задания:
`docker compose run --rm -e PROCESS_COUNTRY=pt racefinder python main.py --once` и
`docker compose run --rm -e PROCESS_COUNTRY=es racefinder python main.py --once`.
`MAX_EVENTS_PER_RUN` и `MAX_WEBSITE_CHECKS_PER_RUN` ограничивают работу за проход
(0 — без лимита); расписание каждого задания задаётся отдельно на уровне запуска.

## Проверка общего импорта PT/ES

WPML и ACF используют JWT Auth (пароль пользователя WordPress нужен для получения
токена). Ошибка связи перевода останавливает обработку строки. Для ES созданный
EN-ID сохраняется до связывания, а повторная обработка восстанавливает связь.

`tests/integration_country_import.py` запускается отдельно в Docker только на
подготовленной одноразовой loopback-копии DEV с private-dir. Он вызывает настоящие
WC/JWT/ACF/WPML API, но использует локальную таблицу и фиксированные тексты.
Обычные тесты: `python -m pytest -q tests` (в Docker).

Для Антонио: найденные ссылки появляются в Missing races ES. Переносить выбранные
мероприятия в общую RACES, ставить COUNTRY=Spain, заполнять RACE NAME (ES),
LOCATION (CITY) как муниципалитет с провинцией (например Badalona, Barcelona),
остальные данные и строки вариантов по прежней схеме. Для вариантов COUNTRY
можно оставить пустым. BOOK URL имеет приоритет перед WEBSITE для кнопки Book.
ID товаров/вариантов руками не переносить между DEV и рабочим сайтом.
Автоматический сбор подробностей по URL в эту задачу не входит.

Оба испанских источника проверены с сервера; ES-монитор остаётся выключенным
до клиентской проверки и рабочего включения. Языки ES+EN подтверждены Антонио.

Статус Published в таблице означает завершённую обработку скриптом. Новые карточки
в WordPress создаются как draft, по существующему PT-процессу; публикация на сайте
выполняется после проверки в WordPress. Эта задача не меняет данное поведение.

## PT + ES + EN для новых мероприятий

Новый режим включается `NEW_EVENT_LANGUAGES=pt,es,en` (значение по умолчанию).
Страна мероприятия выбирает географию и исходный язык, но все три версии сохраняют
одну страну, даты, цены, дистанции и Book. Антонио заполняет исходные данные один раз.
Для прежнего режима новых строк можно явно задать `NEW_EVENT_LANGUAGES=legacy`.

Порядок рабочего включения (на DEV выполнен отдельно от PROD):

1. Установить `wordpress/rf-import-languages.php` в `wp-content/mu-plugins/` WordPress.
   JWT-пользователь импорта должен иметь право `manage_woocommerce`.
   В WPML должны быть активны PT, ES и EN; география и мост страны из ES-ветки
   должны быть установлены до запуска издателя.
2. Указать реальные `pt_parent_id`, `es_parent_id`, `en_parent_id` в каждом элементе
   `CATEGORY_ROOT_MAP_JSON` целевой базы. Для мероприятий Испании нужен `ENABLE_SPAIN=true`.
3. Приостановить плановый проход на время подготовки таблицы. Сначала проверить
   `docker compose run --rm racefinder python prepare_trilingual_sheet.py`, затем
   выполнить ту же команду с `--apply`. Команда добавляет недостающие колонки;
   при первом добавлении `LANGUAGE SCHEME` существующие главные строки получают
   `LEGACY`. Контент и WordPress ID этих строк не меняются. Повтор подготовки
   колонок не переводит новые строки обратно в LEGACY.
4. Запустить новую версию издателя, проверить один проход, затем вернуть расписание.
   Продакшен в рамках DEV-проверки автоматически не переключается.

Новая строка без WordPress ID и `LINK RACEFINDER` получает `LANGUAGE SCHEME=PT_ES_EN`
до создания товаров. Ранее опубликованные строки и строки `LEGACY` сохраняют
свои языки, даже при повторной обработке. Не используйте дату забега как признак
новой публикации. Расширение старых мероприятий требует отдельного явного перехода.

Служебные колонки `LANGUAGE STATE`, `INPUT FINGERPRINT`, `CONTENT FINGERPRINT`,
`THIRD LANGUAGE FINGERPRINT`, `ATTRIBUTE TRANSLATIONS` заполняет скрипт. При сбое `IN_PROGRESS` использует
сохранённые тексты, если исходные данные строки не менялись; динамическая страница
источника не запускает повторную генерацию. После `COMPLETE` новое обновление
снова проверяет источники. ID каждой версии сохраняется сразу после получения. Для принудительного обновления
незавершённого снимка оператор может очистить `CONTENT FINGERPRINT`.
`Published` ставится последним, когда готовы все три версии и вариации.

WordPress-мост повторно использует существующую языковую запись в группе WPML,
включая автоматическую PT-копию испанского оригинала, и отключает для неё
автокопирование. Вариации тоже связываются в WPML, чтобы их ID не менялись
при сохранении оригинала. Третий текст готовится из уже очищенного EN-контента без повторного
сбора источников. Исчезнувшие FAQ/преимущества очищаются; FAQ сохраняют формат Q:/A:.
Переключатель и SEO сайта могут использовать все три настоящих перевода.
Новые карточки по-прежнему создаются черновиками; режим публикации сайта не меняется.

Формат `CATEGORY`/`SUBCATEGORY` не меняется. Издатель сопоставляет названия со
справочником сайта: например, `Ultra marathon` → существующая группа `Ultra Marathons`,
`Sky Running` → `Skyrunning`, `MTB` → существующая группа MTB. Родители, языки и
группы переводов проверяются до импорта и после сохранения. Недостающий язык
добавляется в найденную группу, без создания параллельной категории; неоднозначные
названия останавливают обработку с NOTE. Для этого вместе с издателем обновляется
`rf-import-languages.php`: защищённые маршруты `import-category-catalog`,
`ensure-import-category-group`, `verify-import-categories`. Каталог читается без
фронтовой языковой фильтрации. Группы всех дополнительных категорий вариантов тоже
сохраняются. Очищенный в таблице срок регистрации очищается и в WordPress.

Перед генерацией проверяются прямые ссылки, цены, даты, числовые WP ID и уникальность
вариантов. Даты окончания регистрации указываются в `REGISTRATION DEADLINE`, а не
в служебных ID. Главная строка содержит ID/название и статус Revised, последующие
строки вариантов — без ID, названия и статуса. Если есть командные варианты, пустой `TEAM` означает индивидуальное
участие; смешанные пустые `LICENSE`/`TYPE` отклоняются как неоднозначные. Подписи
значений переводятся на PT/ES/EN и связываются через защищённый маршрут
`ensure-import-terms` (нужна обновлённая версия `rf-import-languages.php`). Родительские
карточки и варианты получают точные языковые ID через `apply-import-options`;
после завершения запроса WCML отдельный запрос проверяет сохранённые ID. Числа,
дистанции и даты не переводятся. Перед успехом издатель повторно читает карточки,
проверяет описания, страну, даты, Book, срок регистрации, число вариантов, цены,
локализованные значения и расписания цен. При несовпадении статус остаётся Revised
с причиной в NOTE; повтор использует сохранённые ID и тексты. Недоступный источник
оставляет `CHECKING_SOURCE` и останавливает обработку; старый текст не подменяет
неудавшееся обновление. Автоматический поиск другого источника сюда не входит.

Приёмка 02.11.2026: 170 Docker-тестов, реальные источники/Google/OpenAI/WPML,
восстановление после сбоя без новой генерации, стабильные ID товаров и вариаций,
защита PT-текста от сохранения ES-оригинала, шесть публичных страниц с Book и
настоящими PT/ES/EN hreflang. Старые карточки не изменены. Новые TEST TRI оставлены
на DEV для просмотра; временные доступы отозваны. Отчёт: docs/trilingual-dev-validation-20261102.json.

Приёмка публикации 04.11.2026: 198 Docker-тестов; два подготовленных мероприятия
Антонио обновлены штатным запуском на DEV без ручной правки товаров. Проверены шесть
публичных страниц и 21 вариация, точные языковые ID справочников, индивидуальное
участие, описания/FAQ, цены и сроки. ID сохранены, повтор Published не пишет в WP,
рабочая таблица не менялась. Отчёт: docs/publication-validation-20261104.json.

Приёмка категорий 07.11.2026: 215 Docker-тестов; все сочетания категорий 20 мероприятий
Антонио сопоставлены без изменения исходных ячеек. Четыре тестовых мероприятия
переобработаны штатным издателем: 12 публичных страниц, 27 вариантов, прежние ID,
правильные иерархии и языки. Восстановлен EN-член старой группы MTB; три пустых
дубля ультрамарафона, созданные прежними тестами, удалены после проверки использования.
Текущая ветка DEV сохранена. Отчёт: docs/category-validation-20261107.json.

Для Running.life и RockTheSport издатель и проверка изменений используют
`ES_HTTP_USER_AGENT` (по умолчанию `RaceFinderMonitor/1.0 (+https://racefinder.es)`),
как испанский монитор. Браузер не требуется; постоянный отказ доступа сразу
фиксируется как ошибка источника, а не передаётся в генерацию описаний.

Проверка двух ES-источников 07.11.2026: реальный монитор записал 1964 кандидата
в `Missing races ES`; две существующие DEV-карточки Антонио обновлены из настоящих
URL (6 переводов, 21 вариант), повтор не пересоздаёт товары. Отчёт:
`docs/es-sources-validation-20261107.json`. Рабочий издатель PROD не переключался.

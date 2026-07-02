"""Общая настройка окружения для тестов.

Конфиг проекта (`_1_google_loader.load_config`) валидируется на импорте и
требует набор обязательных переменных окружения. Здесь мы задаём безопасные
тестовые значения-заглушки, чтобы модули импортировались без реального `.env`,
а тестовый прогон стабильно проходил при любом перезапуске.

Также убираем серверные пути к CA-сертификатам (`SSL_CERT_FILE`,
`REQUESTS_CA_BUNDLE`): если они унаследованы из окружения/`.env`, клиент OpenAI
падает на импорте с FileNotFoundError, потому что таких файлов нет локально.
"""

import os

# Серверные пути к сертификатам ломают инициализацию httpx/OpenAI локально.
for _var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
    os.environ.pop(_var, None)

# Обязательные переменные окружения (значения-заглушки; сеть в тестах мокается).
# setdefault — чтобы не затирать значения, если они уже заданы намеренно.
_ENV_DEFAULTS = {
    "GOOGLE_SPREADSHEET_ID": "test-spreadsheet-id",
    "OPENAI_API_KEY": "test-openai-key",
    "OPENCAGE_API_KEY": "test-opencage-key",
    "WP_URL": "https://example.test",
    "WP_ADMIN_USER": "test-user",
    "WP_ADMIN_PASS": "test-pass",
    "WP_CONSUMER_KEY": "test-consumer-key",
    "WP_CONSUMER_SECRET": "test-consumer-secret",
}
for _key, _value in _ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

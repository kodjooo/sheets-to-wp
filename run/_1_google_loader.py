import json
import logging
import os
import threading
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

def load_config():
    # Загружаем конфигурацию только из переменных окружения
    config = {
        "spreadsheet_id": os.getenv("GOOGLE_SPREADSHEET_ID"),
        "worksheet_name": os.getenv("GOOGLE_WORKSHEET_NAME", "RACES"),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "openai_text_model": os.getenv("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        "openai_second_model": os.getenv("OPENAI_SECOND_MODEL", "gpt-4o-mini"),
        "openai_text_reasoning_effort": os.getenv("OPENAI_TEXT_REASONING_EFFORT"),
        "openai_second_reasoning_effort": os.getenv("OPENAI_SECOND_REASONING_EFFORT"),
        "openai_system_prompt_file": os.getenv("OPENAI_SYSTEM_PROMPT_FILE", "prompts/assistant_system.txt"),
        "openai_second_system_prompt_file": os.getenv(
            "OPENAI_SECOND_SYSTEM_PROMPT_FILE",
            "prompts/second_system.txt",
        ),
        "opencage_api_key": os.getenv("OPENCAGE_API_KEY"),
        "wp_url": os.getenv("WP_URL"),
        "wp_admin_user": os.getenv("WP_ADMIN_USER"),
        "wp_admin_pass": os.getenv("WP_ADMIN_PASS"),
        "consumer_key": os.getenv("WP_CONSUMER_KEY"),
        "consumer_secret": os.getenv("WP_CONSUMER_SECRET"),
        "sleep_seconds": int(os.getenv("SLEEP_SECONDS", "3"))
    }
    
    # Проверяем, что все обязательные переменные заданы
    required_vars = [
        "spreadsheet_id",
        "openai_api_key",
        "opencage_api_key",
        "wp_url",
        "wp_admin_user",
        "wp_admin_pass",
        "consumer_key",
        "consumer_secret",
    ]
    
    missing_vars = [var for var in required_vars if not config.get(var)]
    if missing_vars:
        raise ValueError(f"Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}")
    
    return config

config = load_config()
SPREADSHEET_ID = config["spreadsheet_id"]
WORKSHEET_NAME = config["worksheet_name"]


def _resolve_log_level(value: str | int | None) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        name = value.strip().upper()
        candidate = getattr(logging, name, None)
        if isinstance(candidate, int):
            return candidate
        try:
            return int(name)
        except ValueError:
            return logging.INFO
    return logging.INFO


_LOG_LEVEL = _resolve_log_level(os.getenv("LOG_LEVEL", "INFO"))

_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "google-credentials.json")
_SHEET_CACHE_TTL_SEC = int(os.getenv("GOOGLE_SHEETS_CACHE_TTL_SEC", str(45 * 60)))

_worksheet_cache = None
_worksheet_cache_ts = 0.0
_worksheet_lock = threading.Lock()
_update_retry_attempts = int(os.getenv("GOOGLE_SHEETS_UPDATE_MAX_ATTEMPTS", "3"))
_update_retry_base_delay = float(os.getenv("GOOGLE_SHEETS_UPDATE_BASE_DELAY_SEC", "1"))


def _load_credentials():
    credentials_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if credentials_json:
        try:
            creds_payload = json.loads(credentials_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Переменная окружения GOOGLE_SERVICE_ACCOUNT_JSON содержит некорректный JSON") from exc
        return ServiceAccountCredentials.from_json_keyfile_dict(creds_payload, _SCOPES)

    if not os.path.exists(_CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"Не найден файл с учетными данными Google: {_CREDENTIALS_FILE}. "
            "Укажите корректный путь через GOOGLE_CREDENTIALS_FILE или задайте GOOGLE_SERVICE_ACCOUNT_JSON."
        )

    return ServiceAccountCredentials.from_json_keyfile_name(_CREDENTIALS_FILE, _SCOPES)


def _reset_sheet_cache():
    global _worksheet_cache, _worksheet_cache_ts
    _worksheet_cache = None
    _worksheet_cache_ts = 0.0


def _get_cached_sheet(force_refresh: bool = False):
    global _worksheet_cache, _worksheet_cache_ts

    with _worksheet_lock:
        cache_expired = (time.time() - _worksheet_cache_ts) > _SHEET_CACHE_TTL_SEC
        if not force_refresh and _worksheet_cache and not cache_expired:
            return _worksheet_cache

        creds = _load_credentials()
        client = gspread.authorize(creds)
        worksheet = client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)
        _worksheet_cache = worksheet
        _worksheet_cache_ts = time.time()
        return worksheet


def _get_sheet_with_retry(max_attempts: int = 3, base_delay_sec: int = 2):
    # Пробуем создать подключение к листу с экспоненциальной задержкой между попытками
    last_err = None
    force_refresh = False
    for attempt in range(1, max_attempts + 1):
        try:
            return _get_cached_sheet(force_refresh=force_refresh)
        except Exception as e:
            last_err = e
            force_refresh = True
            _reset_sheet_cache()
            delay = base_delay_sec * (2 ** (attempt - 1))
            logging.warning(f"⚠️ Не удалось инициализировать Google Sheets (попытка {attempt}/{max_attempts}): {e}")
            if attempt < max_attempts:
                logging.info(f"⏳ Повторная попытка через {delay} сек...")
                time.sleep(delay)
    # Если все попытки исчерпаны — пробрасываем исключение
    raise last_err

def load_revised_rows():
    # Загружаем лист с ретраями на случай временных сетевых ошибок
    sheet = _get_sheet_with_retry()
    data = sheet.get_all_records()
    headers = sheet.row_values(1)
    revised_rows = []
    for i, row in enumerate(data):
        if str(row.get("STATUS", "")).strip().lower() == "revised":
            revised_rows.append((i + 2, row))  # +2 из-за заголовка и 1-индексации
    return revised_rows, headers

def load_all_rows():
    # Загружаем лист с ретраями на случай временных сетевых ошибок
    sheet = _get_sheet_with_retry()
    data = sheet.get_all_records()
    headers = sheet.row_values(1)
    all_rows = []
    for i, row in enumerate(data):
        all_rows.append((i + 2, row))  # +2 из-за заголовка
    return all_rows, headers

def update_cell(row_index, column_name, value, headers):
    # Обновляем ячейку с контролируемыми ретраями и переинициализацией клиента при необходимости
    if column_name not in headers:
        logging.error(f"Ошибка при обновлении ячейки {column_name} в строке {row_index}: колонка не найдена в заголовках")
        return

    col_index = headers.index(column_name) + 1
    last_err = None

    for attempt in range(1, _update_retry_attempts + 1):
        try:
            sheet = _get_sheet_with_retry()
            sheet.update_cell(row_index, col_index, value)
            return
        except Exception as err:
            last_err = err
            _reset_sheet_cache()
            if attempt < _update_retry_attempts:
                delay = _update_retry_base_delay * (2 ** (attempt - 1))
                logging.warning(
                    f"⚠️ Не удалось обновить ячейку {column_name} в строке {row_index} (попытка {attempt}/{_update_retry_attempts}): {err}"
                )
                logging.info(f"⏳ Повторная попытка обновления через {delay} сек...")
                time.sleep(delay)

    logging.error(f"Ошибка при обновлении ячейки {column_name} в строке {row_index}: {last_err}")

def update_status_to_published(row_index, headers):
    update_cell(row_index, "STATUS", "Published", headers)

def batch_update_cells(row_index, updates: dict, headers):
    for key, value in updates.items():
        update_cell(row_index, key, value, headers)

def get_logger():
    logging.basicConfig(level=_LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("RaceLogger")
    logger.setLevel(_LOG_LEVEL)
    return logger

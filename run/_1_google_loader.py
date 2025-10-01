import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import logging
import os
import time

def load_config():
    # Загружаем конфигурацию только из переменных окружения
    config = {
        "spreadsheet_id": os.getenv("GOOGLE_SPREADSHEET_ID"),
        "worksheet_name": os.getenv("GOOGLE_WORKSHEET_NAME", "RACES"),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "assistant_id_text": os.getenv("ASSISTANT_ID_TEXT"),
        "assistant_id_second": os.getenv("ASSISTANT_ID_SECOND"),
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
        "spreadsheet_id", "openai_api_key", "assistant_id_text", 
        "opencage_api_key", "wp_url", 
        "wp_admin_user", "wp_admin_pass", "consumer_key", "consumer_secret"
    ]
    
    missing_vars = [var for var in required_vars if not config.get(var)]
    if missing_vars:
        raise ValueError(f"Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}")
    
    return config

config = load_config()
SPREADSHEET_ID = config["spreadsheet_id"]
WORKSHEET_NAME = config["worksheet_name"]

def _create_sheet_client():
    # Ленивая инициализация клиента и листа, чтобы избежать проблем со «старыми» соединениями
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name("google-credentials.json", scope)
    client = gspread.authorize(creds)
    worksheet = client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)
    return worksheet

def _get_sheet_with_retry(max_attempts: int = 3, base_delay_sec: int = 2):
    # Пробуем создать подключение к листу с экспоненциальной задержкой между попытками
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return _create_sheet_client()
        except Exception as e:
            last_err = e
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
    # Обновляем ячейку с лентой ретраев и новой сессией на каждый вызов
    try:
        col_index = headers.index(column_name) + 1
        sheet = _get_sheet_with_retry()
        sheet.update_cell(row_index, col_index, value)
    except Exception as e:
        logging.error(f"Ошибка при обновлении ячейки {column_name} в строке {row_index}: {e}")

def update_status_to_published(row_index, headers):
    update_cell(row_index, "STATUS", "Published", headers)

def batch_update_cells(row_index, updates: dict, headers):
    for key, value in updates.items():
        update_cell(row_index, key, value, headers)

def get_logger():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    return logging.getLogger("RaceLogger")
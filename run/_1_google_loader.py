import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import logging

def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()
SPREADSHEET_ID = config["spreadsheet_id"]
WORKSHEET_NAME = config["worksheet_name"]

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("google-credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)

def load_revised_rows():
    data = sheet.get_all_records()
    headers = sheet.row_values(1)
    revised_rows = []
    for i, row in enumerate(data):
        if str(row.get("STATUS", "")).strip().lower() == "revised":
            revised_rows.append((i + 2, row))  # +2 because of header and 1-indexing
    return revised_rows, headers

def load_all_rows():
    data = sheet.get_all_records()
    headers = sheet.row_values(1)
    all_rows = []
    for i, row in enumerate(data):
        all_rows.append((i + 2, row))  # +2 из-за заголовка
    return all_rows, headers

def update_cell(row_index, column_name, value, headers):
    try:
        col_index = headers.index(column_name) + 1
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
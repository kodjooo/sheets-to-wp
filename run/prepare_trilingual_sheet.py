"""Добавление языковых колонок; первый запуск фиксирует прежние строки как LEGACY."""
import argparse
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from trilingual_import import schema_columns


def preparation(values):
    original = list(values[0]) if values else []
    if len(set(original)) != len(original):
        raise ValueError('В заголовках есть дубли; сначала исправьте их')
    headers = original + [name for name in schema_columns() if name not in original]
    updates = [{'range': 'A1', 'values': [headers]}]
    count = 0
    if 'LANGUAGE SCHEME' not in original:
        status = original.index('STATUS') if 'STATUS' in original else None
        cells = []
        for row in values[1:]:
            parent = status is not None and len(row) > status and bool(str(row[status]).strip())
            cells.append(['LEGACY' if parent else ''])
            count += int(parent)
        if cells:
            start = gspread.utils.rowcol_to_a1(2, headers.index('LANGUAGE SCHEME') + 1)
            updates.append({'range': start, 'values': cells})
    return headers, updates, count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='По умолчанию только проверка без записи')
    args = parser.parse_args()
    scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    inline = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
    credentials = (ServiceAccountCredentials.from_json_keyfile_dict(json.loads(inline), scopes) if inline
        else ServiceAccountCredentials.from_json_keyfile_name(os.getenv('GOOGLE_CREDENTIALS_FILE', 'google-credentials.json'), scopes))
    ws = gspread.authorize(credentials).open_by_key(os.environ['GOOGLE_SPREADSHEET_ID']).worksheet(os.getenv('GOOGLE_WORKSHEET_NAME', 'RACES'))
    values = ws.get_all_values()
    headers, updates, count = preparation(values)
    if args.apply:
        if ws.col_count < len(headers):
            ws.resize(cols=len(headers))
        ws.batch_update(updates, value_input_option='RAW')
    print(json.dumps({'applied': args.apply, 'columns': len(headers), 'existing_events_marked_legacy': count,
                      'worksheet': ws.title}, ensure_ascii=False))


if __name__ == '__main__':
    main()

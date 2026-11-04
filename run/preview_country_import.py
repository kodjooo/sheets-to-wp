"""Проверка экспортированных строк без Sheets/WP/OpenAI и без секретов."""
import argparse
import csv
import json
import os
from pathlib import Path
from country_profile import ES, profile_for_row, validate_spanish_row, activate_profile, reset_profile, primary_metadata
from trilingual_import import language_scheme, required_headers, validate_roots, SCHEME, LANGUAGES
from publication_contract import validate_block


def preview(rows, headers, wp_url):
    report = []
    for number, row in enumerate(rows, 2):
        if str(row.get('STATUS', '')).lower() not in ('revised (complete)', 'revised (incomplete)'):
            continue
        item = {'row': number, 'id': row.get('ID'), 'ready': False}
        token = None
        try:
            profile = profile_for_row(row)
            token = activate_profile(profile)
            if profile == ES:
                validate_spanish_row(row, headers, wp_url, require_enabled=False)
            scheme = language_scheme(row)
            if scheme == SCHEME:
                required_headers(headers)
                validate_roots()
                block = [(number, dict(row))]
                for child_number, child in enumerate(rows[number - 1:], number + 1):
                    if any(str(child.get(key) or '').strip() for key in ('STATUS', 'ID', 'RACE NAME', 'RACE NAME (PT)', 'RACE NAME (ES)')):
                        break
                    if child.get('DISTANCE') or child.get('ATTRIBUTE'):
                        block.append((child_number, dict(child)))
                validate_block(block)
            adapted = profile.prepare_row(row)
            item.update(country=profile.country, languages=list(LANGUAGES) if scheme == SCHEME else [profile.language, 'en'], scheme=scheme,
                        title=adapted.get('RACE NAME (PT)', ''),
                        primary_id=adapted.get('WP PRODUCT ID PT', ''),
                        metadata=primary_metadata(row),
                        book_url=row.get('BOOK URL') or row.get('WEBSITE', ''), ready=True)
        except (ValueError, TypeError) as exc:
            item['error'] = str(exc)
        finally:
            if token is not None:
                reset_profile(token)
        report.append(item)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='CSV или JSON-массив экспортированных строк')
    parser.add_argument('--report', required=True)
    parser.add_argument('--wp-url', default=os.getenv('WP_URL', ''))
    args = parser.parse_args()
    with Path(args.input).open(encoding='utf-8-sig', newline='') as source:
        if args.input.lower().endswith('.csv'):
            reader = csv.DictReader(source)
            rows = list(reader)
            headers = reader.fieldnames or []
        else:
            rows = json.load(source)
            headers = list(dict.fromkeys(key for row in rows for key in row))
    result = preview(rows, headers, args.wp_url)
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f'Проверено: {len(result)}, готово: {sum(item["ready"] for item in result)}')
    raise SystemExit(1 if any(not item['ready'] for item in result) else 0)

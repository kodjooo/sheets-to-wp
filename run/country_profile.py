"""Страна события и адаптер языковых колонок старого PT/EN-пайплайна."""
from contextvars import ContextVar
from dataclasses import dataclass
import json
import os
from urllib.parse import urlsplit


@dataclass(frozen=True)
class CountryProfile:
    code: str
    country: str
    language: str

    def column(self, name):
        return name.replace('(PT)', '(ES)').replace(' ID PT', ' ID ES') if self.code == 'es' else name

    def prepare_row(self, row):
        result = dict(row)
        if self.code == 'es':
            # Совместимость внутренних ключей; в таблицу пишем только ES-колонки.
            for name in ('RACE NAME (PT)', 'SUMMARY (PT)', 'ORG INFO (PT)', 'BENEFITS (PT)',
                         'FAQ (PT)', 'WP PRODUCT ID PT', 'WP VARIATION ID PT'):
                result[name] = row.get(self.column(name), '')
        return result


PT = CountryProfile('pt', 'portugal', 'pt')
ES = CountryProfile('es', 'spain', 'es')
_ACTIVE = ContextVar('race_country', default=PT)


def profile_for_row(row):
    value = str(row.get('COUNTRY') or '').strip().casefold()
    if value in ('', 'pt', 'portugal', 'португалия'):
        return PT
    if value in ('es', 'spain', 'españa', 'espana', 'испания'):
        return ES
    raise ValueError(f'Неизвестная COUNTRY: {value!r}')


def active_profile():
    return _ACTIVE.get()


def activate_profile(profile):
    return _ACTIVE.set(profile)


def reset_profile(token):
    _ACTIVE.reset(token)


def localized_prompt(prompt):
    if active_profile() != ES:
        return prompt
    # Схема *_pt остаётся внутренней: меняется язык значений, а не JSON-ключи.
    replacements = {'португальском': 'испанском', 'португальский': 'испанский',
                    'португальского': 'испанского', 'Portuguese': 'Spanish',
                    'португальских': 'испанских', 'Regulamento ↗': 'Reglamento ↗'}
    for old, new in replacements.items():
        prompt = prompt.replace(old, new)
    return prompt + ('\n\nСтрана мероприятия — Испания. Значения всех полей с суффиксом _pt '
                     'должны быть на ИСПАНСКОМ языке; поля без суффикса — на английском. '
                     'Это совместимая внутренняя схема, португальский перевод не требуется. '
                     'Не копируй факты и географию из примеров; используй только источники события.')


def primary_metadata(row):
    if active_profile() == PT:
        value = row.get('RF_MUNICIPALITY_NAME')
        return [{'key': '_rf_location_municipality_name', 'value': value}] if value else []
    from rf_spain_location import resolve_spanish_location
    municipality, province = resolve_spanish_location(row)
    return [{'key': '_rf_location_country', 'value': 'es'},
            {'key': '_rf_location_municipality_name', 'value': municipality},
            {'key': '_rf_location_province_name', 'value': province}]


def validate_spanish_row(row, headers, wp_url, require_enabled=True):
    if require_enabled and os.getenv('ENABLE_SPAIN', 'false').lower() != 'true':
        raise ValueError('Обработка Испании выключена: ENABLE_SPAIN=false')
    expected_host = os.getenv('SPAIN_WP_HOST', '').strip().lower()
    if not expected_host or urlsplit(wp_url).hostname != expected_host:
        raise ValueError('SPAIN_WP_HOST должен явно совпадать с целевым WordPress')
    required = ['COUNTRY', 'RACE NAME (ES)', 'WP PRODUCT ID ES', 'WP VARIATION ID ES',
                'WP PRODUCT ID EN', 'WP VARIATION ID EN', 'SUMMARY (ES)', 'ORG INFO (ES)',
                'BENEFITS (ES)', 'FAQ (ES)']
    missing = [column for column in required if column not in headers]
    if missing:
        raise ValueError('Отсутствуют колонки: ' + ', '.join(missing))
    if not str(row.get('RACE NAME (ES)') or '').strip():
        raise ValueError('Пустое название RACE NAME (ES)')
    from rf_spain_location import resolve_spanish_location
    resolve_spanish_location(row)
    roots = json.loads(os.getenv('CATEGORY_ROOT_MAP_JSON', '{}'))
    if not isinstance(roots, dict) or not roots or any(
            not isinstance(item, dict) or not str(item.get('es_parent_id', '')).isdigit()
            or not str(item.get('en_parent_id', '')).isdigit()
            or int(item['es_parent_id']) <= 0 or int(item['en_parent_id']) <= 0
            for item in roots.values()):
        raise ValueError('Для Испании нужны es_parent_id/en_parent_id в CATEGORY_ROOT_MAP_JSON')

"""Справочник ES той же версии, что rf-auto-location в kt/53-two-domains."""
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata


def norm(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', text.casefold()).strip()


@lru_cache(maxsize=1)
def directory():
    data = json.loads(Path(__file__).with_name('rf_es_geography.json').read_text())
    index = {}
    for row in data['municipalities']:
        for name in {norm(row['name']), norm(row.get('alt'))} - {''}:
            index.setdefault(name, []).append(row)
    aliases = {'07': ['Islas Baleares', 'Baleares', 'Balears'], '15': ['La Coruña', 'Coruña'],
               '17': ['Gerona'], '20': ['Guipúzcoa'], '25': ['Lérida'], '26': ['Rioja'],
               '32': ['Orense'], '33': ['Principado de Asturias'], '38': ['Tenerife'], '48': ['Vizcaya']}
    provinces = {}
    for code, row in data['provinces'].items():
        names = row['name'].split('/') + [row['name'], row.get('name_en', ''), row.get('name_pt', '')]
        names += aliases.get(code, []) + [code]
        for name in names:
            if norm(name):
                provinces[norm(name)] = code
    return index, provinces, data['provinces']


def resolve_spanish_location(row):
    index, province_aliases, provinces = directory()
    location = str(row.get('MUNICIPALITY') or row.get('LOCATION (CITY)') or '').strip()
    parts = [part.strip() for part in location.split(',') if part.strip()]
    found = index.get(norm(location)) or (index.get(norm(parts[0]), []) if parts else [])
    hint = str(row.get('PROVINCE') or (parts[-1] if len(parts) > 1 else '')).strip()
    code = province_aliases.get(norm(hint)) if hint else None
    if code:
        found = [item for item in found if item['prov'] == code]
    if not found:
        raise ValueError(f'Муниципалитет Испании не найден: {location!r} / {hint!r}')
    if len(found) != 1:
        raise ValueError(f'Неоднозначный муниципалитет {location!r}: заполните PROVINCE')
    municipality = found[0]
    return municipality['name'], provinces[municipality['prov']]['name']

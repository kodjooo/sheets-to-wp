"""Категории из таблицы сопоставляются со справочником, а не создаются по написанию."""
import re
import unicodedata
import requests

from utils import normalize_category_pairs


def norm(value):
    text = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return re.sub(r'[^a-z0-9]+', '', ''.join(c for c in text if not unicodedata.combining(c)))


VOCABULARY = {
    'running': [
        ('Ultra Marathons', 'Ultra Maratonas', 'Ultramaratones', ['Ultra marathon', 'Ultra Maratona', 'Ultramaratón']),
        ('Skyrunning', 'Skyrunning', 'Skyrunning', ['Sky Running']),
        ('Trail Run', 'Trail', 'Trail', ['Trail running']),
        ('Marathon', 'Maratona', 'Maratón', []),
        ('Half Marathon', 'Meia Maratona', 'Media Maratón', []),
        ('Running 10 km', 'Corrida 10 km', 'Carrera 10 km', []),
        ('Running 5 km', 'Corrida 5 km', 'Carrera 5 km', []),
        ('Road Running', 'Corrida de Estrada', 'Carrera en carretera', []),
        ('Walking', 'Caminhada', 'Senderismo', []),
        ('Kids', 'Crianças', 'Infantil', ['Kids race']),
    ],
    'cycling': [('MTB', 'BTT', 'MTB', ['Mountain Bike (MTB)', 'Mountain Biking (MTB / Off-Road)', 'Mountain Biking', 'Mountain Bike'])],
}


def vocabulary(parent, child):
    for en, pt, es, aliases in VOCABULARY.get(norm(parent), []):
        names = [en, pt, es, *aliases]
        if norm(child) in {norm(v) for v in names}:
            return {'en': en, 'pt': pt, 'es': es}, {norm(v) for v in names}
    return None, {norm(child)}


def select_category(catalog, parent, child, roots):
    labels, aliases = vocabulary(parent, child)
    preferred = norm(labels['en'] if labels else child)
    candidates = [c for c in catalog if c.get('lang') in roots
                  and int(c.get('parent') or 0) == int(roots[c['lang']])
                  and norm(c.get('name')) in aliases]
    canonical = [c for c in candidates if c['lang'] == 'en' and norm(c['name']) == preferred]
    if len(canonical) == 1:
        return canonical[0], labels
    if len(canonical) > 1:
        raise ValueError(f'Неоднозначная категория {parent} → {child}: несколько канонических EN записей')
    groups = {}
    for c in candidates:
        ids = {int(c['id']), *(int(x) for x in (c.get('translations') or {}).values() if x)}
        # Все записи одной группы содержат одинаковые ID переводов либо пересекаются.
        matches = [key for key, members in groups.items() if members['ids'] & ids]
        if matches:
            groups[matches[0]]['ids'].update(ids)
        else:
            groups[int(c['id'])] = {'ids': ids, 'source': c}
    if len(groups) != 1:
        raise ValueError(f'Категория {parent} → {child}: нет однозначного соответствия в справочнике сайта')
    return next(iter(groups.values()))['source'], labels


def category_pairs(row, block):
    return normalize_category_pairs([(r.get('CATEGORY') or row.get('CATEGORY'), r.get('SUBCATEGORY')) for _, r in block])


def resolve_categories(config, row, block):
    import json, os
    from _3_create_product import get_jwt_token
    roots_config = {norm(k): v for k, v in json.loads(os.getenv('CATEGORY_ROOT_MAP_JSON', '{}')).items()}
    token = get_jwt_token()
    response = requests.get(config['wp_url'].rstrip('/') + '/wp-json/custom-api/v1/import-category-catalog/',
        headers={'Authorization': 'Bearer ' + token}, timeout=45)
    response.raise_for_status()
    catalog = response.json()
    if not isinstance(catalog, list):
        raise ValueError('WordPress не вернул справочник категорий')
    ids = {lang: [] for lang in ('pt', 'es', 'en')}
    groups = []
    root_groups = {}
    for parent, child in category_pairs(row, block):
        configured = roots_config.get(norm(parent))
        if not configured:
            raise ValueError('CATEGORY отсутствует в настройках: ' + parent)
        roots = {lang: int(configured.get(lang + '_parent_id') or 0) for lang in ids}
        for lang, rid in roots.items():
            matches = [c for c in catalog if int(c['id']) == rid and c.get('lang') == lang and int(c.get('parent') or 0) == 0]
            if len(matches) != 1:
                raise ValueError(f'Неверный корень {parent}/{lang}: ID={rid}')
            if lang == 'en' and norm(matches[0]['name']) != norm(parent):
                raise ValueError('Корень CATEGORY относится к другому виду спорта: ' + parent)
            if any(int(matches[0].get('translations', {}).get(other) or 0) != root_id for other, root_id in roots.items()):
                raise ValueError('Корни CATEGORY не принадлежат одной группе переводов: ' + parent)
            if rid not in ids[lang]:ids[lang].append(rid)
        root_groups[norm(parent)] = roots
        if not child:continue
        source, names = select_category(catalog, parent, child, roots)
        translations = source.get('translations') or {}
        # Не переводим заново уже существующие названия справочника.
        names = names or {lang: next((c['name'] for c in catalog if int(c['id']) == int(translations.get(lang) or (source['id'] if source['lang'] == lang else 0))), '') for lang in ids}
        if any(not names.get(lang) for lang in ids):
            raise ValueError(f'Нет утверждённого перевода категории {parent} → {child}')
        response = requests.post(config['wp_url'].rstrip('/') + '/wp-json/custom-api/v1/ensure-import-category-group/',
            headers={'Authorization': 'Bearer ' + token},
            json={'source_id': int(source['id']), 'roots': roots, 'names': names}, timeout=60)
        response.raise_for_status()
        group = response.json()
        if not group.get('trid'):
            raise ValueError('WordPress не подтвердил группу категории')
        for lang in ids:
            c = group.get('categories', {}).get(lang, {})
            if c.get('lang') != lang or int(c.get('parent') or 0) != roots[lang] or not c.get('id'):
                raise ValueError('WordPress не подтвердил язык/родителя категории ' + lang)
            if c['id'] not in ids[lang]:ids[lang].append(c['id'])
        groups.append(group)
    return {'ids': ids, 'groups': groups, 'roots': list(root_groups.values())}


def verify_categories(config, plan, product_ids):
    from _3_create_product import get_jwt_token
    response = requests.post(config['wp_url'].rstrip('/') + '/wp-json/custom-api/v1/verify-import-categories/',
        headers={'Authorization': 'Bearer ' + get_jwt_token()},
        json={'plan': plan, 'products': product_ids}, timeout=45)
    response.raise_for_status()
    if not response.json().get('verified'):
        raise ValueError('WordPress не подтвердил категории карточек')

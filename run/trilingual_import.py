"""Три языка для новых публикаций: контроль режима, возобновление и единая география."""
import hashlib
import json
import logging
import os
import re
from pathlib import Path

import requests
from publication_contract import validate_block, label_catalog, known_labels
from rf_schedule import parse_datetime
from category_catalog import resolve_categories, verify_categories
from utils import parse_faq_items
from country_profile import (CountryProfile, active_profile, activate_profile,
                             reset_profile, validate_spanish_row, normalize_native_headings)

SCHEME = 'PT_ES_EN'
FIELDS = {'summary': 'SUMMARY', 'org_info': 'ORG INFO', 'benefits': 'BENEFITS', 'faq': 'FAQ'}
LANGUAGES = ('pt', 'es', 'en')


def language_scheme(row):
    marker = str(row.get('LANGUAGE SCHEME') or '').strip().upper()
    if marker:
        if marker not in (SCHEME, 'LEGACY'):
            raise ValueError('Неизвестная LANGUAGE SCHEME: ' + marker)
        return marker
    # Отсутствующий третий ID у старого товара не делает его новым мероприятием.
    if any(str(row.get('WP PRODUCT ID ' + lang.upper()) or '').strip() for lang in LANGUAGES):
        return 'LEGACY'
    if str(row.get('LINK RACEFINDER') or '').strip():
        return 'LEGACY'
    mode = os.getenv('NEW_EVENT_LANGUAGES', 'pt,es,en').strip().lower()
    if mode == 'legacy':
        return 'LEGACY'
    if set(mode.split(',')) != set(LANGUAGES):
        raise ValueError('NEW_EVENT_LANGUAGES должен быть pt,es,en либо legacy')
    return SCHEME


def column(name, lang):
    if name == 'title':
        return 'RACE NAME' if lang == 'en' else 'RACE NAME (' + lang.upper() + ')'
    return FIELDS[name] + ('' if lang == 'en' else ' (' + lang.upper() + ')')


def content(row, lang):
    return {key: row.get(column(key, lang), '') for key in ('title', *FIELDS)}


def validate_translation(payload, source):
    if not isinstance(payload, dict):
        raise ValueError('Перевод должен быть объектом JSON')
    for key in ('title', *FIELDS):
        value = payload.get(key)
        if not isinstance(value, str) or (str(source.get(key) or '').strip() and not value.strip()):
            raise ValueError('В переводе отсутствует поле ' + key)
    source_faq = str(source.get('faq') or '').strip()
    if source_faq and not parse_faq_items(source_faq):
        raise ValueError('Исходный FAQ должен содержать пары Q:/A:')
    if len(parse_faq_items(source_faq)) != len(parse_faq_items(payload['faq'])):
        raise ValueError('В переводе FAQ нарушены количество вопросов или префиксы Q:/A:')
    result = {key: payload[key] for key in ('title', *FIELDS)}
    if str(source.get('title') or '').startswith('TEST ') and not result['title'].startswith('TEST '):
        result['title'] = 'TEST ' + result['title']
    return result


def translate_content(source, target):
    from _2_content_generation import _OPENAI_CLIENT, config
    prompt = (
        'Переведи все значения переданного JSON на ' + ('европейский португальский' if target == 'pt' else 'испанский')
        + '. Верни только завершённый JSON с теми же ключами title, summary, org_info, benefits, faq. '
        'Все значения — строки. Сохрани HTML, URL, имена брендов, даты, числа и факты. '
        'В FAQ сохрани служебные префиксы Q: и A: без перевода; переводи только вопросы и ответы. '
        'Не добавляй информацию. Не меняй страну мероприятия. В названии переводи обычные '
        'обозначения гонок (например Marathon → Maratona для PT), сохраняя собственные имена. '
        'Не добавляй Markdown-обёртку. Пустое значение сохраняй пустым.'
    )
    translated_source = dict(source)
    marker = re.match(r'^(TEST\b(?:\s+(?:ANTONIO|TRI)\b)?\s*(?:[—–-]\s*)?)', source.get('title', ''), re.I)
    prefix = marker.group(0) if marker else ''
    if prefix:
        translated_source['title'] = source['title'][len(prefix):]
    for attempt in range(3):
        response = _OPENAI_CLIENT.responses.create(
            model=config['openai_second_model'],
            input=[{'role': 'system', 'content': [{'type': 'input_text', 'text': prompt}]},
                   {'role': 'user', 'content': [{'type': 'input_text', 'text': json.dumps(translated_source, ensure_ascii=False)}]}],
        )
        try:
            result = json.loads(response.output_text)
            if prefix and isinstance(result, dict) and isinstance(result.get('title'), str):
                result['title'] = prefix + result['title']
            return validate_translation(result, source)
        except ValueError:
            if attempt == 2:
                raise


def write_content(product_id, data):
    from _3_create_product import _build_acf_fields_partial, send_acf_data, get_jwt_token
    fields = _build_acf_fields_partial(data)
    faq = parse_faq_items(data.get('FAQ (PT)', ''))
    # В новом режиме очищаем исчезнувшие FAQ/преимущества и проверяем ответ ACF.
    fields.update(event_short_description=data['SUMMARY (PT)'], organizer_description=data['ORG INFO (PT)'],
                  race_benefits=data['BENEFITS (PT)'], event_faq_headline='FAQ' if faq else '', event_faq_items=faq)
    response = send_acf_data(product_id, {'fields': fields}, get_jwt_token())
    response.raise_for_status()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def input_snapshot(row, block, native):
    keys = ('COUNTRY', 'CATEGORY', 'SUBCATEGORY', 'LOCATION', 'LOCATION (CITY)', 'MUNICIPALITY',
            'PROVINCE', 'WEBSITE', 'REGULATIONS', 'BOOK URL', 'EVENT START DATE', 'EVENT END DATE',
            'EVENT START TIME', 'REGISTRATION DEADLINE', 'DISTANCE', 'PRICE', 'PRICE CHANGES',
            'TEAM', 'TYPE', 'LICENSE', 'RACE START DATE', 'RACE START TIME', 'ATTRIBUTE', 'VALUE')
    return {'input': {k: row.get(k, '') for k in keys}, 'native_title': row.get(column('title', native)),
            'variations': [{k: child.get(k, '') for k in keys if k != 'COUNTRY'} for _, child in block[1:]]}


def source_fingerprint(row, block, website, regulations, pdf, native):
    return digest({'inputs': input_snapshot(row, block, native), 'website': website, 'regulations': regulations,
                   'pdf': hashlib.sha256(Path(pdf).read_bytes()).hexdigest() if pdf else ''})


def auth_token(config):
    from _3_create_product import get_jwt_token
    return get_jwt_token()


def ensure_translation(config, origin, lang, existing=None):
    from _3_create_product import get_jwt_token
    response = requests.post(
        config['wp_url'].rstrip('/') + '/wp-json/custom-api/v1/ensure-language/',
        headers={'Authorization': 'Bearer ' + (config.get('_import_jwt') or get_jwt_token())},
        json={'original_id': int(origin), 'lang_code': lang, 'existing_id': int(existing) if existing else 0}, timeout=45)
    response.raise_for_status()
    data = response.json()
    if data.get('language') != lang or not data.get('independent') or not data.get('id'):
        raise ValueError('WordPress не подтвердил самостоятельный перевод ' + lang)
    return int(data['id'])


def link_variations(config, source_id, target_id, lang, allow_missing=False):
    from _3_create_product import get_jwt_token
    response = requests.post(config['wp_url'].rstrip('/') + '/wp-json/custom-api/v1/link-variation-language/',
        headers={'Authorization': 'Bearer ' + (config.get('_import_jwt') or get_jwt_token())},
        json={'original_id': int(source_id), 'translated_id': int(target_id), 'lang_code': lang}, timeout=45)
    if allow_missing and response.status_code == 404:
        return
    response.raise_for_status()
    if not response.json().get('linked'):
        raise ValueError('WPML не подтвердил связь вариаций')


def schema_columns():
    columns = ['LANGUAGE SCHEME', 'LANGUAGE STATE', 'INPUT FINGERPRINT', 'CONTENT FINGERPRINT', 'THIRD LANGUAGE FINGERPRINT', 'ATTRIBUTE TRANSLATIONS', 'COUNTRY', 'NOTE', 'STATUS']
    for lang in LANGUAGES:
        columns.extend(column(key, lang) for key in ('title', *FIELDS))
        columns.extend(('WP PRODUCT ID ' + lang.upper(), 'WP VARIATION ID ' + lang.upper()))
    return columns


def ensure_terms(config, specs, attr_ids):
    response = requests.post(config['wp_url'].rstrip('/') + '/wp-json/custom-api/v1/ensure-import-terms/',
        headers={'Authorization': 'Bearer ' + config['_import_jwt']},
        json={'items': [{'attribute_id': attr_ids[name], 'labels': labels} for name, value, labels in specs]}, timeout=90)
    response.raise_for_status()
    items = response.json().get('items')
    if not isinstance(items, list) or len(items) != len(specs):
        raise ValueError('WordPress не подтвердил полный справочник вариантов')
    for item in items:
        if any(not isinstance(item.get(lang), dict) or not item[lang].get('id') or not item[lang].get('name') for lang in LANGUAGES):
            raise ValueError('WordPress не подтвердил переводы значения')
    return {(name, value): item for (name, value, _), item in zip(specs, items)}


def attribute_id(name):
    from _5_taxonomy_and_attributes import get_or_create_attribute
    return get_or_create_attribute(name)


def apply_options(config, ids, entries, mappings=None):
    items = []
    for lang, pid in ids.items():
        options = {}
        variations = []
        for entry in entries[lang]:
            selected = []
            for attr in entry['attributes']:
                options.setdefault(attr['id'], [])
                if attr['term_id'] not in options[attr['id']]:
                    options[attr['id']].append(attr['term_id'])
                selected.append({'id': attr['id'], 'term_id': attr['term_id']})
            if mappings:
                variations.append({'id': mappings[lang][entry['row_index']], 'attributes': selected})
        items.append({'product_id': pid, 'language': lang,
                      'attributes': [{'id': aid, 'term_ids': tids} for aid, tids in options.items()], 'variations': variations})
    for verify_only in (False, True):
        response = requests.post(config['wp_url'].rstrip('/') + '/wp-json/custom-api/v1/apply-import-options/',
            headers={'Authorization': 'Bearer ' + config['_import_jwt']}, json={'items': items, 'verify_only': verify_only}, timeout=120)
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            try:
                detail = response.json()
            except ValueError:
                detail = {}
            raise ValueError('Проверка языковых ID: ' + str(detail.get('code', response.status_code)) + ' ' + str(detail.get('message', ''))) from error
        if not response.json().get('verified'):
            raise ValueError('WordPress не подтвердил точные языковые ID вариантов')


def verify_publication(config, ids, row, entries, mappings, attr_ids):
    from decimal import Decimal
    from datetime import datetime
    from _6_create_variations import _load_all_variations
    for lang, pid in ids.items():
        response = requests.get(config['wp_url'].rstrip('/') + '/wp-json/wc/v3/products/' + str(pid),
            params={'lang': lang}, auth=(config['consumer_key'], config['consumer_secret']), timeout=45)
        response.raise_for_status()
        product = response.json()
        meta = {item['key']: item['value'] for item in product.get('meta_data', [])}
        expected = {'event_country': active_profile().country, 'event_short_description': row[column('summary', lang)],
                    'organizer_description': row[column('org_info', lang)], 'race_benefits': row.get(column('benefits', lang), ''),
                    'event_ticket_url': row.get('BOOK URL') or row.get('WEBSITE', '')}
        faq = parse_faq_items(row.get(column('faq', lang), ''))
        expected['event_faq_headline'] = 'FAQ' if faq else ''
        if str(meta.get('event_faq_items') or '0') != str(len(faq)):
            raise ValueError('Проверка карточки ' + lang + ': неверное количество вопросов FAQ')
        for number, item in enumerate(faq):
            expected.update({'event_faq_items_' + str(number) + '_' + key: value for key, value in item.items()})
        for key, field in [('EVENT START DATE', 'event_date_start'), ('EVENT END DATE', 'event_date_end')]:
            normalized, _ = parse_datetime(row.get(key))
            expected[field] = datetime.strptime(normalized, '%Y-%m-%d %H:%M').strftime('%Y%m%d')
        if any(str(meta.get(key, '')) != str(value) for key, value in expected.items()):
            wrong = [key for key, value in expected.items() if str(meta.get(key, '')) != str(value)]
            raise ValueError('Проверка карточки ' + lang + ': не сохранились ' + ', '.join(wrong))
        deadline, error = parse_datetime(product.get('miss_events', {}).get('registration_deadline'))
        if error or (deadline or '') != row['RF_REGISTRATION_DEADLINE']:
            raise ValueError('Проверка карточки ' + lang + ': неверный срок регистрации')
        actual = _load_all_variations(pid, lang)
        if {int(v['id']) for v in actual} != set(mappings[lang].values()):
            raise ValueError('Проверка карточки ' + lang + ': лишние или отсутствующие варианты')
        by_id = {int(v['id']): v for v in actual}
        for entry in entries[lang]:
            variant = by_id[mappings[lang][entry['row_index']]]
            wanted = {attr_ids[a['name']]: a['option'] for a in entry['attributes']}
            got = {int(a.get('id', 0)): a.get('option') for a in variant.get('attributes', [])}
            if variant.get('regular_price') in (None, '') or got != wanted or Decimal(variant['regular_price']) != Decimal(entry['regular_price']):
                raise ValueError('Проверка варианта ' + lang + ': не совпали цена или локализованные значения')
            def schedule_key(items):
                result = []
                for item in items:
                    moment, error = parse_datetime(item.get('datetime'))
                    if error or not moment:
                        raise ValueError('Не прочиталось расписание цены')
                    result.append((moment, Decimal(str(item['price']))))
                return sorted(result)
            if schedule_key(variant.get('miss_events', {}).get('price_schedule') or []) != schedule_key(entry['price_schedule']):
                raise ValueError('Проверка варианта ' + lang + ': неверное расписание цены')


def required_headers(headers):
    missing = sorted(set(schema_columns()).difference(headers))
    if missing:
        raise ValueError('Для трёх языков отсутствуют колонки: ' + ', '.join(missing))


def validate_roots():
    roots = json.loads(os.getenv('CATEGORY_ROOT_MAP_JSON', '{}'))
    for lang in LANGUAGES:
        if not roots or any(not isinstance(value, dict) or int(value.get(lang + '_parent_id') or 0) <= 0 for value in roots.values()):
            raise ValueError('Отсутствует корневая категория ' + lang)


def process_trilingual(m, index, original, following, headers):
    """Старый двухъязычный проход не меняется; новый режим фиксируется до первой записи WP."""
    required_headers(headers)
    country = active_profile()
    native = country.language
    third = 'pt' if native == 'es' else 'es'
    row = dict(original)
    config = m.load_config()
    block = [(index, row)]
    for child_index, child in following:
        if any(str(child.get(key) or '').strip() for key in ('STATUS', 'ID', 'RACE NAME', 'RACE NAME (PT)', 'RACE NAME (ES)')):
            break
        if child.get('DISTANCE') or child.get('ATTRIBUTE'):
            block.append((child_index, dict(child)))

    def write(updates, row_index=index):
        # Запись явных языковых колонок без адаптера PT→ES.
        m._batch_update_cells(row_index, updates, headers)
        if row_index == index:
            row.update(updates)
    row['_RF_RESUME'] = row.get('LANGUAGE STATE') == 'IN_PROGRESS'
    try:
        if not str(row.get(column('title', native)) or '').strip():
            raise ValueError('Не заполнено название мероприятия на исходном языке')
        validate_roots()
        if native == 'es':
            validate_spanish_row(row, headers, config['wp_url'])
        validate_block(block)
        write({'LANGUAGE SCHEME': SCHEME, 'LANGUAGE STATE': 'IN_PROGRESS' if row['_RF_RESUME'] else 'CHECKING_SOURCE'})
        row['_RF_CATEGORY_PLAN'] = resolve_categories(config, row, block)
        _process(m, config, country, third, index, row, block, headers, write)
    except Exception as error:
        write({'NOTE': 'Trilingual import incomplete: ' + str(error)[:350]})
        raise


def _process(m, config, country, third, index, row, block, headers, write):
    native = country.language
    input_hash = digest(input_snapshot(row, block, native))
    resumed = (row.get('_RF_RESUME') and row.get('INPUT FINGERPRINT') == input_hash
               and bool(row.get('CONTENT FINGERPRINT')))
    if resumed:
        try:
            validate_translation(content(row, native), content(row, 'en'))
        except ValueError:
            resumed = False
    regulations_url = m.unwrap_google_viewer_url(row.get('REGULATIONS', ''))
    website, regulations, pdf = '', '', None
    if resumed:
        fingerprint = row['CONTENT FINGERPRINT']
    else:
        website, _ = m.extract_text_from_url(row.get('WEBSITE', ''))
        regulations, pdf = m.extract_text_from_url(regulations_url) if regulations_url else ('', None)
        errors = m.validate_source_texts(website_url=row.get('WEBSITE', ''), website_text=website,
            regulations_url=regulations_url, regulations_text=regulations, regulations_pdf_path=pdf)
        if errors:
            raise ValueError('; '.join(errors))
        fingerprint = source_fingerprint(row, block, website, regulations, pdf, native)
    ready = bool(resumed or row.get('CONTENT FINGERPRINT') == fingerprint)
    ready = ready and all(str(row.get(column(k, lang)) or '').strip() for lang in (native, 'en') for k in ('title', 'summary', 'org_info'))
    if ready:
        try:
            validate_translation(content(row, native), content(row, 'en'))
        except ValueError:
            ready = False
    if not ready:
        write({'CONTENT FINGERPRINT': ''})
    # Старые тексты не становятся снимком нового запуска до успешного чтения источника.
    write({'LANGUAGE STATE': 'IN_PROGRESS'})
    if not ready:
        if m.SKIP_AI:
            raise ValueError('Трёхъязычный импорт требует настоящие тексты: SKIP_AI должен быть false')
        title = m.translate_title_to_en(row.get(column('title', native), ''))
        if not title:
            raise ValueError('Не получено английское название')
        if row[column('title', native)].startswith('TEST ') and not title.startswith('TEST '):
            title = 'TEST ' + title
        file_ids = []
        if pdf:
            with open(pdf, 'rb') as source:
                file_ids.append(m.openai.files.create(file=source, purpose='assistants').id)
        first = m.call_openai_assistant(m.build_first_assistant_prompt(
            regulations_url=regulations_url, regulations_text=regulations, website_text=website), file_ids=file_ids)
        if first is None:
            raise ValueError('Не получены факты мероприятия')
        first = m.normalize_regulations_link_block(first, regulations_url)
        result = None
        for _ in range(1 + max(0, m.PT_RETRY_ATTEMPTS)):
            result = m.call_second_openai_assistant(first, regulations_hint='REGULATIONS LINK: ' + (regulations_url or '(empty)'))
            if result and not m.get_missing_pt_fields(result):
                break
        if not result or m.get_missing_pt_fields(result):
            raise ValueError('Не получены полные основные переводы')
        result = normalize_native_headings(result)
        updates = {'RACE NAME': title}
        for lang, suffix in [('en', ''), (native, '_pt')]:
            for key in FIELDS:
                value = result.get(key + suffix) or ''
                if isinstance(value, list):
                    value = '\n'.join(str(x) for x in value)
                if key == 'org_info':
                    value = m._append_cancellation_block(value, result.get('cancellation' + suffix, ''), lang)
                updates[column(key, lang)] = value
        if not all(str(updates.get(column(k, lang)) or '').strip() for lang in (native, 'en') for k in ('summary', 'org_info')):
            raise ValueError('Пустое обязательное описание')
        if not m.SKIP_IMAGE:
            image = m.generate_image(result['image_prompt'])
            if not image:
                raise ValueError('Не удалось сгенерировать обложку; проверьте доступ модели изображений или SKIP_IMAGE')
            updates.update({'IMAGE URL': image.get('url', ''), 'IMAGE ID': image.get('id') or ''})
        updates.update({k: v for k, v in {'ORGANIZER NAME': result.get('organizer_name', ''),
            'ORGANIZER EMAIL': m._extract_valid_emails(result.get('organizer_email', ''))}.items() if k in headers})
        write(updates)
        validate_translation(content(row, native), content(row, 'en'))
        # Отпечаток сохраняется после всех полей: частичная запись не считается готовым контентом.
        write({'INPUT FINGERPRINT': input_hash, 'CONTENT FINGERPRINT': fingerprint})
    if row[column('title', native)].startswith('TEST ') and not str(row.get('RACE NAME') or '').startswith('TEST '):
        write({'RACE NAME': 'TEST ' + row['RACE NAME']})
    english = content(row, 'en')
    third_hash = digest(english)
    third_ready = row.get('THIRD LANGUAGE FINGERPRINT') == third_hash
    if english['title'].startswith('TEST ') and not str(row.get(column('title', third)) or '').startswith('TEST '):
        third_ready = False
    if third_ready:
        try:
            validate_translation(content(row, third), english)
        except ValueError:
            third_ready = False
    if not third_ready:
        write({'THIRD LANGUAGE FINGERPRINT': ''})
        translated = validate_translation(translate_content(english, third), english)
        write({column(key, third): value for key, value in translated.items()})
        write({'THIRD LANGUAGE FINGERPRINT': third_hash})

    lat, lon = m.get_coordinates_with_city_fallback(row.get('LOCATION', ''), row.get('LOCATION (CITY)', ''))
    row.update(LAT=lat if lat is not None else '', LON=lon if lon is not None else '')
    if lat is None or lon is None:
        raise ValueError('Не определены координаты')
    row['RF_MUNICIPALITY_NAME'] = m.resolve_municipality(row.get('LOCATION (CITY)', '')) if country.code == 'pt' else ''
    deadline, errors = m.parse_datetime(row.get('REGISTRATION DEADLINE', ''))
    if errors:
        raise ValueError('Registration deadline: ' + str(errors))
    row['RF_REGISTRATION_DEADLINE'] = deadline or ''
    row['extra_categories'] = []
    for _, variation in block:
        if variation.get('CATEGORY'):
            for item in (m.parse_subcategory_values(variation.get('SUBCATEGORY')) or [None]):
                pair = (variation['CATEGORY'], item)
                if pair not in row['extra_categories']:
                    row['extra_categories'].append(pair)
    catalog = label_catalog(block, row.get('ATTRIBUTE TRANSLATIONS'))
    write({'ATTRIBUTE TRANSLATIONS': json.dumps(catalog, ensure_ascii=False)})
    config['_import_jwt'] = auth_token(config)
    term_specs = []
    attr_ids = {}
    pairs = [('Distance', 'DISTANCE'), ('Team', 'TEAM'), ('Type', 'TYPE'), ('License', 'LICENSE'),
             ('Race Start Date', 'RACE START DATE'), ('Race Start Time', 'RACE START TIME')]
    for _, variation in block:
        for name, col in pairs + ([(variation['ATTRIBUTE'], 'VALUE')] if variation.get('ATTRIBUTE') and variation.get('VALUE') else []):
            value = str(variation.get(col) or '').strip()
            if value and (name, value) not in [(s[0], s[1]) for s in term_specs]:
                term_specs.append((name, value, catalog.get(value) or known_labels(value) or dict.fromkeys(LANGUAGES, value)))
                if name not in attr_ids:
                    attr_ids[name] = attribute_id(name)
    terms = ensure_terms(config, term_specs, attr_ids)
    entries = {}
    for lang in LANGUAGES:
        entries[lang] = []
        for row_index, variation in block:
            attrs = []
            current_pairs = list(pairs)
            if variation.get('ATTRIBUTE') and variation.get('VALUE'):
                current_pairs.append((variation['ATTRIBUTE'], 'VALUE'))
            for name, col in current_pairs:
                value = variation.get(col)
                if value:
                    label = terms[(name, str(value).strip())][lang]['name']
                    attrs.append({'name': name, 'option': label, 'id': attr_ids[name], 'term_id': terms[(name, str(value).strip())][lang]['id']})
            schedule, errors = m.parse_price_changes(variation.get('PRICE CHANGES', ''))
            if errors:
                raise ValueError('Price schedule: ' + str(errors))
            entries[lang].append({'row_index': row_index, 'existing_variation_id': variation.get('WP VARIATION ID ' + lang.upper(), ''),
                'regular_price': str(variation.get('PRICE') or '0'), 'attributes': attrs, 'price_schedule': schedule, 'strict_schedule': True})
        signatures = [tuple(sorted((a['name'], a['option']) for a in entry['attributes'])) for entry in entries[lang]]
        if len(signatures) != len(set(signatures)):
            raise ValueError('Перевод сделал варианты неразличимыми: ' + lang)
    # При возобновлении связываем сохранённые варианты до сохранения родителя WCML.
    for row_index, variation in block:
        source_id = variation.get('WP VARIATION ID ' + native.upper())
        for lang in LANGUAGES:
            target_id = variation.get('WP VARIATION ID ' + lang.upper())
            if lang != native and source_id and target_id:
                link_variations(config, source_id, target_id, lang, allow_missing=True)
    ids = {}
    # Все родительские записи обновляются до окончательной сверки вариаций WPML.
    for lang in (native, 'en', third):
        profile = CountryProfile(country.code, country.country, lang)
        token = activate_profile(profile)
        try:
            data = dict(row)
            for key in ('title', *FIELDS):
                data['RACE NAME (PT)' if key == 'title' else FIELDS[key] + ' (PT)'] = row[column(key, lang)]
            data['CATEGORY_IDS_PT'] = [{'id': cid} for cid in row['_RF_CATEGORY_PLAN']['ids'][lang]]
            def checkpoint(pid):
                write({'WP PRODUCT ID ' + lang.upper(): pid})
            existing = row.get('WP PRODUCT ID ' + lang.upper())
            if lang != native:
                existing = ensure_translation(config, ids[native], lang, existing)
                checkpoint(existing)
            pid = m.create_product_pt_primary(data, existing_product_id=existing or None, on_created=checkpoint)
            if not pid:
                raise ValueError('Не получен ID версии ' + lang)
            checkpoint(pid)
            ids[lang] = pid
            write_content(pid, data)
            apply_options(config, {lang: pid}, entries)
        finally:
            reset_profile(token)
    mappings = {}
    for lang in (native, 'en', third):
        mapping = m.sync_variations_by_ids(ids[lang], entries[lang], lang=lang)
        mappings[lang] = mapping
        m.reapply_price_schedules(ids[lang], entries[lang], lang=lang)
        for row_index, vid in mapping.items():
            write({'WP VARIATION ID ' + lang.upper(): vid}, row_index)
    for row_index, source_id in mappings[native].items():
        for lang in LANGUAGES:
            if lang != native:
                link_variations(config, source_id, mappings[lang][row_index], lang)
    apply_options(config, ids, entries, mappings)
    primary = requests.get(config['wp_url'].rstrip('/') + '/wp-json/wc/v3/products/' + str(ids[native]),
        auth=(config['consumer_key'], config['consumer_secret']), timeout=45)
    primary.raise_for_status()
    verify_publication(config, ids, row, entries, mappings, attr_ids)
    verify_categories(config, row['_RF_CATEGORY_PLAN'], ids)
    incomplete = str(row.get('STATUS') or '').lower() == m.STATUS_REVISED_INCOMPLETE.lower()
    updates = {'LINK RACEFINDER': primary.json().get('permalink', ''), 'NOTE': ''}
    if incomplete:
        updates['WEBSITE SNAPSHOT HASH'] = m.compute_website_hash(row.get('WEBSITE', ''))[0]
    write(updates)
    write({'LANGUAGE STATE': 'COMPLETE'})
    write({'STATUS': m.STATUS_PUBLISHED_INCOMPLETE if incomplete else m.STATUS_PUBLISHED})
    logging.info('Трёхъязычная обработка завершена: ID=%s products=%s', row.get('ID'), ids)

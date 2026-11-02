"""Три языка для новых публикаций: контроль режима, возобновление и единая география."""
import hashlib
import json
import logging
import os
from pathlib import Path

import requests
from utils import parse_faq_items
from country_profile import (CountryProfile, active_profile, activate_profile,
                             reset_profile, validate_spanish_row)

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
    return {key: payload[key] for key in ('title', *FIELDS)}


def translate_content(source, target):
    from _2_content_generation import _OPENAI_CLIENT, config
    prompt = (
        'Переведи все значения переданного JSON на ' + ('европейский португальский' if target == 'pt' else 'испанский')
        + '. Верни только завершённый JSON с теми же ключами title, summary, org_info, benefits, faq. '
        'Все значения — строки. Сохрани HTML, URL, имена брендов, даты, числа и факты. '
        'В FAQ сохрани служебные префиксы Q: и A: без перевода; переводи только вопросы и ответы. '
        'Не добавляй информацию. Не меняй страну мероприятия. Сохрани префикс TEST, если он есть. '
        'Не добавляй Markdown-обёртку. Пустое значение сохраняй пустым.'
    )
    for attempt in range(3):
        response = _OPENAI_CLIENT.responses.create(
            model=config['openai_second_model'],
            input=[{'role': 'system', 'content': [{'type': 'input_text', 'text': prompt}]},
                   {'role': 'user', 'content': [{'type': 'input_text', 'text': json.dumps(source, ensure_ascii=False)}]}],
        )
        try:
            return validate_translation(json.loads(response.output_text), source)
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
    columns = ['LANGUAGE SCHEME', 'LANGUAGE STATE', 'INPUT FINGERPRINT', 'CONTENT FINGERPRINT', 'THIRD LANGUAGE FINGERPRINT', 'COUNTRY', 'NOTE', 'STATUS']
    for lang in LANGUAGES:
        columns.extend(column(key, lang) for key in ('title', *FIELDS))
        columns.extend(('WP PRODUCT ID ' + lang.upper(), 'WP VARIATION ID ' + lang.upper()))
    return columns


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
    if not str(row.get(column('title', native)) or '').strip():
        raise ValueError('Не заполнено название мероприятия на исходном языке')
    config = m.load_config()
    validate_roots()
    if native == 'es':
        validate_spanish_row(row, headers, config['wp_url'])
    block = [(index, row)]
    for child_index, child in following:
        if str(child.get('STATUS') or '').strip():
            break
        if child.get('DISTANCE') or child.get('ATTRIBUTE'):
            block.append((child_index, dict(child)))

    def write(updates, row_index=index):
        # Запись явных языковых колонок без адаптера PT→ES.
        m._batch_update_cells(row_index, updates, headers)
        if row_index == index:
            row.update(updates)
    row['_RF_RESUME'] = row.get('LANGUAGE STATE') == 'IN_PROGRESS'
    write({'LANGUAGE SCHEME': SCHEME, 'LANGUAGE STATE': 'IN_PROGRESS'})
    try:
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
        if m.SKIP_AI:
            raise ValueError('Трёхъязычный импорт требует настоящие тексты: SKIP_AI должен быть false')
        title = m.translate_title_to_en(row.get(column('title', native), ''))
        if not title:
            raise ValueError('Не получено английское название')
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
            updates.update({'IMAGE URL': image.get('url', ''), 'IMAGE ID': image.get('id') or ''})
        updates.update({k: v for k, v in {'ORGANIZER NAME': result.get('organizer_name', ''),
            'ORGANIZER EMAIL': m._extract_valid_emails(result.get('organizer_email', ''))}.items() if k in headers})
        write(updates)
        validate_translation(content(row, native), content(row, 'en'))
        # Отпечаток сохраняется после всех полей: частичная запись не считается готовым контентом.
        write({'INPUT FINGERPRINT': input_hash, 'CONTENT FINGERPRINT': fingerprint})
    english = content(row, 'en')
    third_hash = digest(english)
    third_ready = row.get('THIRD LANGUAGE FINGERPRINT') == third_hash
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
    attributes, entries = {}, {}
    for lang in LANGUAGES:
        entries[lang] = []
        for row_index, variation in block:
            attrs = []
            pairs = [('Distance', 'DISTANCE'), ('Team', 'TEAM'), ('Type', 'TYPE'), ('License', 'LICENSE'),
                     ('Race Start Date', 'RACE START DATE'), ('Race Start Time', 'RACE START TIME')]
            if variation.get('ATTRIBUTE') and variation.get('VALUE'):
                pairs.append((variation['ATTRIBUTE'], 'VALUE'))
            for name, col in pairs:
                value = variation.get(col)
                if value:
                    attrs.append({'name': name, 'option': str(value)})
                    attributes.setdefault(name, [])
                    if str(value) not in attributes[name]:
                        attributes[name].append(str(value))
            schedule, errors = m.parse_price_changes(variation.get('PRICE CHANGES', ''))
            if errors:
                raise ValueError('Price schedule: ' + str(errors))
            entries[lang].append({'row_index': row_index, 'existing_variation_id': variation.get('WP VARIATION ID ' + lang.upper(), ''),
                'regular_price': str(variation.get('PRICE') or '0'), 'attributes': attrs, 'price_schedule': schedule})
    attributes = m.normalize_attribute_payload(attributes)
    config['_import_jwt'] = auth_token(config)
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
            data['CATEGORY_IDS_PT'] = m._build_pt_category_ids_from_en(data)
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
            m.assign_attributes_to_product(pid, attributes, lang=lang)
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
    primary = requests.get(config['wp_url'].rstrip('/') + '/wp-json/wc/v3/products/' + str(ids[native]),
        auth=(config['consumer_key'], config['consumer_secret']), timeout=45)
    primary.raise_for_status()
    incomplete = str(row.get('STATUS') or '').lower() == m.STATUS_REVISED_INCOMPLETE.lower()
    updates = {'LINK RACEFINDER': primary.json().get('permalink', ''), 'NOTE': ''}
    if incomplete:
        updates['WEBSITE SNAPSHOT HASH'] = m.compute_website_hash(row.get('WEBSITE', ''))[0]
    write(updates)
    write({'LANGUAGE STATE': 'COMPLETE'})
    write({'STATUS': m.STATUS_PUBLISHED_INCOMPLETE if incomplete else m.STATUS_PUBLISHED})
    logging.info('Трёхъязычная обработка завершена: ID=%s products=%s', row.get('ID'), ids)

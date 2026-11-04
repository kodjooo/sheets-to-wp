"""Проверка подготовленных строк и согласованные подписи вариантов PT/ES/EN."""
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from rf_schedule import parse_datetime, parse_price_changes


def validate_block(block):
    parent = block[0][1]
    if not str(parent.get('CATEGORY') or '').strip():
        raise ValueError('Заполните CATEGORY мероприятия')
    for key in ('WEBSITE', 'REGULATIONS', 'BOOK URL'):
        value = str(parent.get(key) or '').strip()
        if value and (urlsplit(value).scheme not in ('https', 'http') or not urlsplit(value).hostname):
            raise ValueError(f'{key}: требуется прямая ссылка http/https')
    if not str(parent.get('WEBSITE') or parent.get('REGULATIONS') or '').strip():
        raise ValueError('Заполните WEBSITE или REGULATIONS для описания мероприятия')
    dates = []
    for key in ('EVENT START DATE', 'EVENT END DATE'):
        value, error = parse_datetime(parent.get(key))
        if error or not value:
            raise ValueError(f'{key}: требуется корректная дата')
        dates.append(datetime.strptime(value, '%Y-%m-%d %H:%M'))
    if dates[1] < dates[0]:
        raise ValueError('EVENT END DATE раньше EVENT START DATE')
    deadline, error = parse_datetime(parent.get('REGISTRATION DEADLINE'))
    if error:
        raise ValueError('REGISTRATION DEADLINE: ' + error)
    seen_ids = {lang: set() for lang in ('pt', 'es', 'en')}
    for index, row in block:
        if not str(row.get('DISTANCE') or '').strip() and not (row.get('ATTRIBUTE') and row.get('VALUE')):
            raise ValueError(f'Row {index}: заполните DISTANCE или ATTRIBUTE/VALUE')
        for key, value in row.items():
            if key.startswith(('WP PRODUCT ID ', 'WP VARIATION ID ')) and str(value or '').strip():
                if not re.fullmatch(r'[1-9][0-9]*', str(value).strip()):
                    raise ValueError(f'Row {index}, {key}: требуется числовой ID; даты укажите в REGISTRATION DEADLINE')
                if key.startswith('WP VARIATION ID '):
                    lang = key.rsplit(' ', 1)[-1].lower()
                    if lang in seen_ids:
                        if str(value) in seen_ids[lang]:
                            raise ValueError(f'Row {index}: повторяется ID вариации {lang}')
                        seen_ids[lang].add(str(value))
        try:
            price = Decimal(str(row.get('PRICE', '')).strip())
            if not price.is_finite() or price < 0:
                raise InvalidOperation
        except InvalidOperation:
            raise ValueError(f'Row {index}, PRICE: требуется цена числом, включая 0 для бесплатного участия')
        _, error = parse_price_changes(row.get('PRICE CHANGES'))
        if error:
            raise ValueError(f'Row {index}, PRICE CHANGES: {error}')
        for key in ('RACE START DATE', 'RACE START TIME'):
            value = str(row.get(key) or '').strip()
            if value:
                _, error = parse_datetime(value if key.endswith('DATE') else '2000-01-01 ' + value)
                if error:
                    raise ValueError(f'Row {index}, {key}: {error}')
    # Пустой TEAM при наличии команд — отдельный одиночный вариант, а не wildcard.
    has_teams = any(str(r.get('TEAM') or '').strip() for _, r in block)
    for _, row in block:
        if has_teams and not str(row.get('TEAM') or '').strip():
            row['TEAM'] = 'Individual'
    for key in ('LICENSE', 'TYPE'):
        if any(str(r.get(key) or '').strip() for _, r in block) and any(not str(r.get(key) or '').strip() for _, r in block):
            raise ValueError(f'{key}: заполните значение для каждого варианта, чтобы исключить wildcard')
    signatures = set()
    for index, row in block:
        signature = tuple(str(row.get(k) or '').strip().casefold() for k in
                          ('DISTANCE', 'TEAM', 'TYPE', 'LICENSE', 'RACE START DATE', 'RACE START TIME', 'ATTRIBUTE', 'VALUE'))
        if signature in signatures:
            raise ValueError(f'Row {index}: одинаковые варианты участия; цена не различает варианты')
        signatures.add(signature)
    return deadline or ''


_GROUPS = [
    ('Individual', 'Individual', 'Individual', ['Individual participation', 'Individual entry', 'Individuais', 'Individuale']),
    ('Pairs', 'Duplas', 'Parejas', ['Dobles', 'Doubles', 'Dupla', 'Pair']),
    ('Teams of 4', 'Equipas de 4', 'Equipos de 4', ['Team of 4']),
    ('Teams of 6', 'Equipas de 6', 'Equipos de 6', ['Team of 6']),
    ('Relay', 'Estafetas', 'Relevos', ['Relay team']),
    ('Road running', 'Corrida de estrada', 'Carrera en carretera', ['Carrera de carretera']),
    ('Trail running', 'Corrida de montanha', 'Carrera de montaña', ['Trail run']),
    ('Walking', 'Caminhada', 'Senderismo', ['Caminata']),
    ('Licensed', 'Federado', 'Federado', ['Afiliado', 'Con licencia válida']),
    ('Unlicensed', 'Não federado', 'No federado', ['Sin licencia válida']),
    ('Kids', 'Crianças', 'Infantil', ['Carreras infantiles']),
    ('MTB', 'BTT', 'MTB', []),
]


def known_labels(value):
    text = str(value).strip()
    if re.fullmatch(r'[\d\s.,:/+-]+(?:\s*(?:km|m|mi))?', text, flags=re.I):
        return dict.fromkeys(('en', 'pt', 'es'), text)
    for en, pt, es, aliases in _GROUPS:
        if text.casefold() in {x.casefold() for x in (en, pt, es, *aliases)}:
            return {'en': en, 'pt': pt, 'es': es}
    return None


def translate_labels(values):
    from _2_content_generation import _OPENAI_CLIENT, config
    response = _OPENAI_CLIENT.responses.create(model=config['openai_second_model'], input=[
        {'role': 'system', 'content': 'Translate race registration option labels. Return JSON array in the same order, each object has en, pt (European Portuguese), es. Keep all numbers and meaning; no extra text.'},
        {'role': 'user', 'content': json.dumps(values, ensure_ascii=False)}])
    result = json.loads(response.output_text)
    if not isinstance(result, list) or len(result) != len(values):
        raise ValueError('Не получен полный перевод вариантов участия')
    for source, labels in zip(values, result):
        if not isinstance(labels, dict) or any(not isinstance(labels.get(l), str) or not labels[l].strip() for l in ('pt', 'es', 'en')):
            raise ValueError('Пустой перевод варианта участия')
        if any(re.findall(r'\d+(?:[.,]\d+)?', labels[l]) != re.findall(r'\d+(?:[.,]\d+)?', source) for l in ('pt', 'es', 'en')):
            raise ValueError('Перевод изменил числа в варианте участия')
    return result


def label_catalog(block, cached):
    try:
        cache = json.loads(cached or '{}')
    except (ValueError, TypeError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    values = list(dict.fromkeys(str(r.get(k) or '').strip() for _, r in block
                               for k in ('TEAM', 'TYPE', 'LICENSE', 'VALUE') if str(r.get(k) or '').strip()))
    result, unknown = {}, []
    for value in values:
        labels = known_labels(value) or cache.get(value)
        if isinstance(labels, dict) and all(isinstance(labels.get(l), str) and labels[l].strip() for l in ('pt', 'es', 'en')):
            result[value] = labels
        else:
            unknown.append(value)
    if unknown:
        result.update(zip(unknown, translate_labels(unknown)))
    return result

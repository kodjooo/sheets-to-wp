"""Общее содержимое PT/EN/ES в прежних двух запросах генерации и очистки."""
from country_profile import localized_prompt, active_profile, SPANISH_HEADINGS
from utils import parse_faq_items
import re

PROMPT_MARKER = '\n\n=== PT_ES_EN EXTENSION ===\n'
GENERATION_CONTRACT = 'joint-pt-es-en-v1'
SUFFIXES = {'en': '', 'pt': '_pt', 'es': '_es'}


def content_prompt(text, trilingual=False):
    original, marker, extension = text.partition(PROMPT_MARKER)
    if not trilingual:
        return localized_prompt(original.strip())
    if not marker:
        raise ValueError('Промпт не содержит расширения PT_ES_EN')
    return original + '\n\n' + extension + '\nСтрана события: ' + active_profile().country + '.'


def validate_joint_result(payload):
    if not isinstance(payload, dict):
        raise ValueError('Ожидался общий JSON PT/EN/ES')
    result = dict(payload)
    for lang, suffix in SUFFIXES.items():
        for key in ('title', 'summary', 'org_info', 'benefits', 'faq', 'cancellation'):
            name = key + suffix
            value = result.get(name)
            if key == 'benefits' and isinstance(value, list) and all(isinstance(x, str) for x in value):
                value = '\n'.join(value)
            if not isinstance(value, str):
                raise ValueError('В общем ответе отсутствует поле ' + name)
            if key in ('title', 'summary') and not value.strip():
                raise ValueError('Пустое обязательное поле ' + name)
            result[name] = value
    for key in ('summary', 'org_info', 'benefits', 'faq', 'cancellation'):
        present = [bool(result[key + suffix].strip()) for suffix in SUFFIXES.values()]
        if any(present) and not all(present):
            raise ValueError('Нарушен паритет трёх языков: ' + key)
    faq_counts = [len(parse_faq_items(result['faq' + suffix])) for suffix in SUFFIXES.values()]
    if len(set(faq_counts)) != 1 or any(result['faq'+s].strip() and not parse_faq_items(result['faq'+s]) for s in SUFFIXES.values()):
        raise ValueError('В FAQ трёх языков различаются вопросы либо префиксы Q:/A:')
    text = result['org_info_es']
    for original, translated in SPANISH_HEADINGS.items():
        text = re.sub(r'(<strong>\s*)' + re.escape(original) + r'(\s*:?\s*</strong>)',
                      lambda m: m[1] + translated + m[2], text, flags=re.I)
    result['org_info_es'] = text
    return result


def joint_response_format():
    properties = {}
    for lang, suffix in SUFFIXES.items():
        for key in ('title', 'summary', 'org_info', 'benefits', 'faq', 'cancellation'):
            properties[key+suffix] = ({'anyOf':[{'type':'string'},{'type':'array','items':{'type':'string'}}]}
                                      if key=='benefits' else {'type':'string'})
            language={'en':'English','pt':'European Portuguese','es':'Spanish'}[lang]
            properties[key+suffix]['description']=language+' only. Country does not change the language of this field.'
            if key=='title':
                properties[key+suffix]['description']+=' Translate generic race terms: '+{'en':'Maratón / Maratona → Marathon','pt':'Maratón / Marathon → Maratona','es':'Marathon / Maratona → Maratón'}[lang]+'. Preserve proper names and TEST markers.'
    properties.update({key:{'type':'string'} for key in ('image_prompt','organizer_name','organizer_email')})
    return {'format':{'type':'json_schema','name':'race_content_pt_es_en','strict':True,
        'schema':{'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}}}


def validate_cleaned_result(first, cleaned):
    source = validate_joint_result(first)
    if not isinstance(cleaned, dict):
        raise ValueError('Ожидался общий результат очистки')
    result = dict(cleaned)
    # По исходному промпту эти поля очиститель обязан вернуть без изменений.
    for suffix in SUFFIXES.values():
        for key in ('title', 'summary', 'faq', 'cancellation'):
            result[key+suffix] = source[key+suffix]
    for key in ('image_prompt', 'organizer_name', 'organizer_email'):
        if key in source:
            result[key] = source[key]
    return validate_joint_result(result)

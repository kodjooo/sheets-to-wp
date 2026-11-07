"""Единая HTTP-политика подтверждённых испанских источников без браузера."""
import os
from urllib.parse import urlsplit

ES_HOSTS = frozenset({'running.life', 'www.running.life', 'web.rockthesport.com'})
DEFAULT_ES_USER_AGENT = 'RaceFinderMonitor/1.0 (+https://racefinder.es)'


def source_headers(url, headers):
    result = dict(headers)
    if (urlsplit(url).hostname or '').lower() in ES_HOSTS:
        result['User-Agent'] = os.getenv('ES_HTTP_USER_AGENT') or DEFAULT_ES_USER_AGENT
    return result


def validate_source_response(url, text, headers):
    if (urlsplit(url).hostname or '').lower() not in ES_HOSTS:
        return
    # Заглушка с HTTP 200 не должна попадать в генерацию или хеш страницы.
    lowered = text[:20000].lower()
    if (headers.get('cf-mitigated', '').lower() == 'challenge'
            or '<title>just a moment' in lowered
            or '<title>attention required' in lowered):
        raise ValueError('Источник вернул страницу защиты вместо данных мероприятия')

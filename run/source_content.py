"""Текст выбранной карточки ES без соседних мероприятий и с адресами документов."""
import json
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def extract_spanish_card(url, html):
    host = (urlsplit(url).hostname or '').lower()
    if host not in ('running.life', 'www.running.life', 'web.rockthesport.com'):
        return None
    soup = BeautifulSoup(html, 'html.parser')
    if host.endswith('running.life'):
        title = soup.find('h1')
        description = soup.select_one('main .markdown-text')
        if title is None or description is None:
            raise ValueError('Running.life: не найдены заголовок и описание карточки')
        parts = [title.get_text(' ', strip=True)]
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or script.get_text())
            except (TypeError, ValueError):
                continue
            if isinstance(data, dict) and data.get('@type') in ('Event', 'SportsEvent'):
                parts.append(json.dumps(data, ensure_ascii=False))
        roots = [description]
    else:
        roots = soup.select('#section-product-showcase, #section-product-information')
        if not roots or not soup.find('h1'):
            raise ValueError('RockTheSport: не найдена основная часть карточки')
        parts = []
    links = set()
    for root in roots:
        for node in root.select('script, style, nav, form, iframe'):
            node.decompose()
        parts.append(root.get_text(' ', strip=True))
        for anchor in root.select('a[href]'):
            target = urljoin(url, anchor['href'])
            if urlsplit(target).scheme in ('http', 'https'):
                links.add((anchor.get_text(' ', strip=True), target))
    if links:
        parts.append('Source links:\n' + '\n'.join(f'{label}: {target}' for label, target in sorted(links)))
    return '\n\n'.join(parts).strip()

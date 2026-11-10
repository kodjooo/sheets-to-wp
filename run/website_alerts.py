"""Короткий дайджест изменений страниц без превышения лимита Telegram."""


def _short(value, limit):
    text = ' '.join(str(value or '').split())
    return text if len(text) <= limit else text[:limit-1] + '…'


def format_website_changes(changes, worksheet_url, checked_at=None):
    lines = ['Website changes detected', f'Changed event pages: {len(changes)}']
    if checked_at:
        lines.append('Last check: ' + _short(checked_at, 48))
    lines.append('')
    # Полные WEBSITE каждой строки доступны в RACES, а не в одном длинном сообщении.
    for item in changes[:10]:
        lines.append('• #' + _short(item.get('id'), 24) + ' — ' + _short(item.get('race'), 96))
    if len(changes) > 10:
        lines.append(f'… and {len(changes)-10} more in RACES')
    lines.extend(['', 'Review RACES: ' + str(worksheet_url)])
    return '\n'.join(lines)

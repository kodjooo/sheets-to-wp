"""Парсинг «Registration deadline» и «Scheduled price changes» из таблицы.

Значения уходят в мету плагина miss-events через штатный WC REST payload
`miss_events` (registration_deadline — на товаре, price_schedule — на вариации).

- Дата/время принимаем: `YYYY-MM-DD HH:MM(:SS)`, `DD/MM/YYYY HH:MM`, ISO
  (`YYYY-MM-DDTHH:MM`). Если время не указано — по умолчанию 18:00.
- Нормализуем к `YYYY-MM-DD HH:MM` (плагин это принимает).
- Price changes — одна ячейка, записи через `;` или перенос строки,
  каждая: `<дата время> = <цена>`.
"""

import re
from datetime import datetime

DEFAULT_TIME = "18:00"

_DT_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
]
_DATE_ONLY_FORMATS = ["%Y-%m-%d", "%d/%m/%Y"]


def parse_datetime(value: str, default_time: str = DEFAULT_TIME):
    """Возвращает (normalized 'YYYY-MM-DD HH:MM', error|None). Пусто → (None, None)."""
    s = str(value or "").strip().replace("\n", " ")
    if not s:
        return None, None
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M"), None
        except ValueError:
            continue
    # только дата — подставляем время по умолчанию
    for fmt in _DATE_ONLY_FORMATS:
        try:
            d = datetime.strptime(s, fmt)
            return f"{d.strftime('%Y-%m-%d')} {default_time}", None
        except ValueError:
            continue
    return None, f"unrecognized date/time: '{s}'"


def parse_price(value: str):
    s = str(value or "").strip().replace(",", ".")
    s = re.sub(r"[^0-9.]", "", s)
    if s == "" or s.count(".") > 1:
        return None
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return None


def parse_price_changes(cell: str):
    """Разбирает ячейку в список {datetime, price} + список ошибок."""
    raw = str(cell or "").strip()
    if not raw:
        return [], []
    entries = [e.strip() for e in re.split(r"[;\n]+", raw) if e.strip()]
    result, errors = [], []
    for entry in entries:
        if "=" not in entry:
            errors.append(f"missing '=' in entry: '{entry}'")
            continue
        dt_part, price_part = entry.split("=", 1)
        dt, err = parse_datetime(dt_part)
        price = parse_price(price_part)
        if err or not dt:
            errors.append(err or f"invalid date in '{entry}'")
            continue
        if price is None:
            errors.append(f"invalid price in '{entry}'")
            continue
        result.append({"datetime": dt, "price": price})
    return result, errors

"""Резолв муниципалитета Португалии из поля «Location (City)».

Используется автоматикой публикации: по «Location (City)» (формат обычно
«Municipality, District») определяем канонический муниципалитет из списка
сайта (плагин event-location, 308 муниципалитетов). Дальше это имя пишется в
мету товара `_rf_location_municipality_name`, а mu-plugin `rf-auto-location`
на стороне WP достраивает district+region, ставит термы и синхронит в EN.

Список `rf_municipalities.json` сгенерирован из таксономии сайта
(rf_pt_municipality). Обновить при изменении набора муниципалитетов:
выгрузить {нормализованное_имя: каноничное_имя} из термов rf_pt_municipality.
"""

import json
import os
import re
import unicodedata

_MAP = None


def _load() -> dict:
    global _MAP
    if _MAP is None:
        path = os.path.join(os.path.dirname(__file__), "rf_municipalities.json")
        try:
            with open(path, encoding="utf-8") as fh:
                _MAP = json.load(fh)
        except Exception:
            _MAP = {}
    return _MAP


def _norm(value: str) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower().replace("\n", " "))
    return re.sub(r"\s+", " ", s).strip()


def resolve_municipality(location_city: str) -> str | None:
    """Возвращает каноничное имя муниципалитета или None.

    Пробуем оба токена «Municipality, District» (муниципалитет может быть
    как первым, так и вторым), плюс строку целиком (когда запятой нет).
    """
    mapping = _load()
    if not mapping:
        return None
    raw = str(location_city or "").replace("\n", " ")
    tokens = [t.strip() for t in raw.split(",") if t.strip()] or [raw]
    for token in tokens:
        canonical = mapping.get(_norm(token))
        if canonical:
            return canonical
    return None

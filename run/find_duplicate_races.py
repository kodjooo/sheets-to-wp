"""Разовый аудит: поиск дублей гонок на racefinder.pt.

Задача (по запросу клиента): найти события, которые заведены на сайте более
одного раза, и выдать список на ручное ревью. Скрипт НИЧЕГО не меняет на сайте
и в основной таблице — только читает данные и записывает отчёт в отдельную
вкладку Google-таблицы.

Источник данных:
- WooCommerce REST API (все статусы: publish + draft) — что реально заведено
  на сайте (язык по умолчанию — PT, чтобы не считать EN-переводы дублями).
- Google-таблица (колонка WEBSITE) — внешний URL гонки, сопоставляется с
  продуктом по WP PRODUCT ID для критерия «одинаковый внешний URL».

Критерии дубля (комбинируются, чтобы снизить ложные срабатывания):
- похожесть нормализованного названия (fuzzy);
- совпадение даты старта (обязательный подтверждающий сигнал: одинаковое имя
  при РАЗНОЙ дате — это, как правило, легитимные ежегодные издания, не дубль);
- совпадение внешнего URL;
- близость по координатам.

Запуск (с загруженным окружением проекта):
    python find_duplicate_races.py                 # полный прогон + запись вкладки
    python find_duplicate_races.py --dry-run        # без записи, только stdout
    python find_duplicate_races.py --limit 300      # ограничить число продуктов (отладка)
    python find_duplicate_races.py --tab "DUPLICATES REVIEW"
"""

import argparse
import logging
import re
import sys
import time
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

import gspread
import requests

from _1_google_loader import load_config, _load_credentials, load_all_rows, SPREADSHEET_ID

logger = logging.getLogger("DuplicateFinder")

# --- Пороги (консервативные: лучше пропустить сомнительное, чем нафлудить) ---
NAME_SIM_MIN = 0.62           # минимальная похожесть имени, чтобы пара вообще рассматривалась
SCORE_REPORT_THRESHOLD = 65   # ниже этого балла пара не попадает в отчёт
GEO_MAX_KM = 10.0             # «та же локация» — в пределах этого радиуса

# Слова-шум: ТОЛЬКО артикли/предлоги и маркеры издания. Названия форматов
# (maratona, meia, trail, triatlo, btt...) НЕ убираем — они различают гонки
# (полумарафон ≠ марафон). Слишком частые токены и так отсекаются порогом
# частоты при генерации пар-кандидатов.
STOPWORDS = {
    "de", "da", "do", "dos", "das", "e", "the", "of", "and",
    "a", "o", "os", "as", "em", "no", "na", "edicao", "edition", "ed",
}

# Римские числа (издания): убираем как отдельные токены.
_ROMAN_RE = re.compile(r"^[ivxlcdm]+$")


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize_name(name: str) -> tuple[str, frozenset]:
    """Возвращает (нормализованная_строка, множество значимых токенов)."""
    if not name:
        return "", frozenset()
    text = _strip_accents(str(name)).lower()
    # убираем годы и порядковые издания (9ª, 19º, 3°, 1st ...)
    text = re.sub(r"\b(19|20)\d{2}\b", " ", text)
    text = re.sub(r"\b\d+\s*[º°ªao]?\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    raw_tokens = [t for t in text.split() if t]
    tokens = [
        t for t in raw_tokens
        if t not in STOPWORDS and not _ROMAN_RE.match(t) and len(t) > 1
    ]
    # если после чистки ничего не осталось — откатываемся к сырым токенам
    if not tokens:
        tokens = raw_tokens
    return " ".join(sorted(tokens)), frozenset(tokens)


def name_similarity(a_norm: str, a_tokens: frozenset, b_norm: str, b_tokens: frozenset) -> float:
    """Комбинируем строковое сходство и Жаккар по токенам (устойчиво к перестановке слов)."""
    if not a_norm or not b_norm:
        return 0.0
    seq = SequenceMatcher(None, a_norm, b_norm).ratio()
    if a_tokens and b_tokens:
        jaccard = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
    else:
        jaccard = 0.0
    return max(seq, jaccard)


def normalize_url(url: str) -> str:
    if not url:
        return ""
    u = str(url).strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def parse_date(value: str) -> str:
    """Приводим дату к YYYY-MM-DD для сравнения. Пусто, если распарсить нельзя."""
    if not value:
        return ""
    s = str(value).strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)
    if m:
        d, mth, y = m.group(1), m.group(2), m.group(3)
        return f"{y}-{int(mth):02d}-{int(d):02d}"
    return ""


def haversine_km(lat1, lon1, lat2, lon2) -> float | None:
    import math
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (TypeError, ValueError):
        return None
    if 0 == lat1 == lon1 or 0 == lat2 == lon2:
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# --------------------------- Загрузка данных ---------------------------

def _meta_map(product: dict) -> dict:
    return {m.get("key"): m.get("value") for m in product.get("meta_data", []) if isinstance(m, dict)}


def fetch_all_products(config: dict, lang: str = "pt", limit: int | None = None) -> list[dict]:
    """Тянем все продукты (все статусы) через WC REST API с пагинацией."""
    base = config["wp_url"].rstrip("/") + "/wp-json/wc/v3/products"
    auth = (config["consumer_key"], config["consumer_secret"])
    timeout = config.get("wcapi_timeout_sec", 20)
    per_page = 100
    page = 1
    products: list[dict] = []
    while True:
        params = {"per_page": per_page, "page": page, "status": "any"}
        if lang:
            params["lang"] = lang
        resp = _get_with_retry(base, auth, params, timeout, config)
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        products.extend(batch)
        logger.info("📦 Загружено продуктов: %d (страница %d)", len(products), page)
        if limit and len(products) >= limit:
            products = products[:limit]
            break
        total_pages = resp.headers.get("X-WP-TotalPages")
        if total_pages and page >= int(total_pages):
            break
        if len(batch) < per_page:
            break
        page += 1
    return products


def _get_with_retry(url, auth, params, timeout, config):
    attempts = int(config.get("wcapi_max_attempts", 4))
    base_delay = float(config.get("wcapi_base_delay_sec", 1.5))
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, auth=auth, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_err = exc
            logger.warning("⚠️ WC API ошибка (попытка %d/%d): %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_err


def build_product_id_to_website(rows) -> dict:
    """Карта WP PRODUCT ID (PT и EN) -> внешний WEBSITE из Google-таблицы."""
    mapping: dict[str, str] = {}
    for _row_index, row in rows:
        website = str(row.get("WEBSITE", "")).strip()
        if not website:
            continue
        for col in ("WP PRODUCT ID PT", "WP PRODUCT ID EN"):
            pid = str(row.get(col, "")).strip()
            if pid:
                mapping.setdefault(pid, website)
    return mapping


def build_records(products: list[dict], id_to_website: dict) -> list[dict]:
    records = []
    seen_ids = set()
    for p in products:
        pid = str(p.get("id", ""))
        # WC API (пагинация + WPML) может вернуть один и тот же продукт несколько
        # раз — иначе он спарится «сам с собой». Оставляем только первое вхождение.
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        meta = _meta_map(p)
        name = (p.get("name") or "").strip()
        norm, tokens = normalize_name(name)
        website = id_to_website.get(pid, "") or meta.get("event_ticket_url", "") or ""
        records.append({
            "id": pid,
            "name": name,
            "status": p.get("status", ""),
            "permalink": p.get("permalink", ""),
            "date": parse_date(meta.get("event_date_start", "")),
            "location": (meta.get("event_location_text") or "").strip(),
            "lat": meta.get("event_latitude", ""),
            "lon": meta.get("event_longitude", ""),
            "website": normalize_url(website),
            "website_raw": website,
            "norm": norm,
            "tokens": tokens,
        })
    return records


# --------------------------- Поиск дублей ---------------------------

def candidate_pairs(records: list[dict]):
    """Кандидаты — продукты, у которых есть общий значимый токен ИЛИ общий URL.

    Инвертированный индекс вместо полного O(n^2): резко сокращает число пар и
    ловит совпадения при разном порядке слов.
    """
    token_index = defaultdict(list)
    url_index = defaultdict(list)
    for i, rec in enumerate(records):
        for tok in rec["tokens"]:
            token_index[tok].append(i)
        if rec["website"]:
            url_index[rec["website"]].append(i)

    seen = set()
    # слишком частые токены (напр. общий бренд) пропускаем как блокирующие
    for tok, idxs in token_index.items():
        if len(idxs) > 60:
            continue
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                pair = (idxs[a], idxs[b])
                if pair not in seen:
                    seen.add(pair)
                    yield pair
    for _url, idxs in url_index.items():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                pair = (idxs[a], idxs[b]) if idxs[a] < idxs[b] else (idxs[b], idxs[a])
                if pair not in seen:
                    seen.add(pair)
                    yield pair


# Минимальная похожесть имени, когда дата НЕ подтверждает совпадение
# (обе даты известны и равны — самый сильный сигнал; иначе имя должно быть почти идентичным).
NAME_SIM_STRICT = 0.88


def score_pair(x: dict, y: dict) -> tuple[int, list[str]]:
    sim = name_similarity(x["norm"], x["tokens"], y["norm"], y["tokens"])
    same_url = bool(x["website"]) and x["website"] == y["website"]
    if sim < NAME_SIM_MIN and not same_url:
        return 0, []

    xd, yd = x["date"], y["date"]
    # Логика клиента: разные известные даты => разные издания, а не дубль.
    if xd and yd and xd != yd:
        return 0, []
    same_date = bool(xd) and xd == yd

    dist = haversine_km(x["lat"], x["lon"], y["lat"], y["lon"])
    geo_close = dist is not None and dist <= GEO_MAX_KM

    # Гейт: если дата НЕ подтверждает (хотя бы одна отсутствует), требуем
    # почти идентичное имя И хотя бы один вспомогательный сигнал (URL/гео).
    # Это отсекает «общий URL федерации» у разных ивентов.
    if same_date:
        if sim < NAME_SIM_MIN and not same_url:
            return 0, []
    else:
        if sim < NAME_SIM_STRICT or not (same_url or geo_close):
            return 0, []

    reasons = []
    score = sim * 50
    reasons.append(f"имя~{int(sim * 100)}%")
    if same_date:
        score += 30
        reasons.append(f"дата={xd}")
    if same_url:
        score += 25
        reasons.append("URL совпадает")
    if geo_close:
        score += 15
        reasons.append(f"гео≈{dist:.1f}км")

    return int(min(score, 100)), reasons


class UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def find_duplicate_groups(records: list[dict]):
    uf = UnionFind(len(records))
    pair_info = {}
    n_pairs = 0
    for i, j in candidate_pairs(records):
        n_pairs += 1
        score, reasons = score_pair(records[i], records[j])
        if score >= SCORE_REPORT_THRESHOLD:
            uf.union(i, j)
            pair_info[(i, j)] = (score, reasons)
    logger.info("🔍 Проверено пар-кандидатов: %d, совпадений выше порога: %d", n_pairs, len(pair_info))

    groups = defaultdict(list)
    members = set()
    for (i, j) in pair_info:
        members.add(i)
        members.add(j)
    for idx in members:
        groups[uf.find(idx)].append(idx)

    result = []
    for root, idxs in groups.items():
        idxs = sorted(idxs)
        # лучший балл внутри группы — для сортировки
        best = max(
            (pair_info[(a, b)][0] for a in idxs for b in idxs if (a, b) in pair_info),
            default=0,
        )
        reasons = set()
        for a in idxs:
            for b in idxs:
                if (a, b) in pair_info:
                    reasons.update(pair_info[(a, b)][1])
        result.append({"indices": idxs, "score": best, "reasons": sorted(reasons)})
    result.sort(key=lambda g: g["score"], reverse=True)
    return result


# --------------------------- Отчёт ---------------------------

REPORT_HEADER = [
    "GROUP", "SCORE", "MATCH REASONS", "PRODUCT ID", "STATUS",
    "RACE NAME", "DATE", "LOCATION", "WEBSITE", "PERMALINK",
]


def build_report_rows(groups, records) -> list[list]:
    rows = [REPORT_HEADER]
    for gi, group in enumerate(groups, start=1):
        for idx in group["indices"]:
            r = records[idx]
            rows.append([
                gi,
                group["score"],
                ", ".join(group["reasons"]),
                r["id"],
                r["status"],
                r["name"],
                r["date"],
                r["location"],
                r["website_raw"],
                r["permalink"],
            ])
    return rows


def write_report_tab(rows: list[list], tab_name: str):
    creds = _load_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    try:
        ws = spreadsheet.worksheet(tab_name)
        ws.clear()
        logger.info("♻️ Очищена существующая вкладка '%s'", tab_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=max(len(rows) + 10, 100), cols=len(REPORT_HEADER))
        logger.info("➕ Создана вкладка '%s'", tab_name)
    ws.update(rows)  # raw=True по умолчанию — пишем значения как есть
    logger.info("✅ Записано строк в отчёт: %d (групп-дублей: %d)", len(rows) - 1, max(int(rows[-1][0]) if len(rows) > 1 else 0, 0))


def main():
    parser = argparse.ArgumentParser(description="Поиск дублей гонок на racefinder.pt (только отчёт).")
    parser.add_argument("--dry-run", action="store_true", help="Не записывать вкладку, только вывести сводку.")
    parser.add_argument("--limit", type=int, default=None, help="Ограничить число продуктов (для отладки).")
    parser.add_argument("--lang", default="pt", help="Язык продуктов WC (по умолчанию pt).")
    parser.add_argument("--tab", default="DUPLICATES REVIEW", help="Имя вкладки для отчёта.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    config = load_config()

    logger.info("⬇️ Читаю продукты WooCommerce (все статусы, lang=%s)...", args.lang)
    products = fetch_all_products(config, lang=args.lang, limit=args.limit)
    logger.info("Всего продуктов: %d", len(products))

    logger.info("⬇️ Читаю Google-таблицу для сопоставления внешних URL...")
    rows, _headers = load_all_rows()
    id_to_website = build_product_id_to_website(rows)
    logger.info("Сопоставлено WP PRODUCT ID -> WEBSITE: %d", len(id_to_website))

    records = build_records(products, id_to_website)
    groups = find_duplicate_groups(records)

    logger.info("=== Найдено групп подозреваемых дублей: %d ===", len(groups))
    for gi, group in enumerate(groups[:20], start=1):
        names = [f"#{records[i]['id']} {records[i]['name']!r} [{records[i]['status']}]" for i in group["indices"]]
        logger.info("Группа %d (score=%d, %s): %s", gi, group["score"], ", ".join(group["reasons"]), " | ".join(names))

    report_rows = build_report_rows(groups, records)
    if args.dry_run:
        logger.info("DRY-RUN: вкладка не записана. Строк в отчёте было бы: %d", len(report_rows) - 1)
        return 0
    write_report_tab(report_rows, args.tab)
    return 0


if __name__ == "__main__":
    sys.exit(main())

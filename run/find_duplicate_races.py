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
# Дубль = ПОЧТИ ИДЕНТИЧНОЕ имя. Разные суб-события одного организатора в один
# день (общий URL/локация, разные названия) — НЕ дубли, поэтому имя обязательно.
NAME_SIM_MIN = 0.85           # минимальная похожесть имени для попадания в отчёт
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
    """Приводим дату к YYYY-MM-DD для сравнения. Пусто, если распарсить нельзя.

    WooCommerce хранит event_date_start в формате YYYYMMDD (напр. '20260920'),
    но поддерживаем также YYYY-MM-DD и DD/MM/YYYY на всякий случай.
    """
    if not value:
        return ""
    s = str(value).strip()

    def _valid(y, mth, d):
        return 1 <= mth <= 12 and 1 <= d <= 31

    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)  # YYYYMMDD
    if m:
        y, mth, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid(y, mth, d):
            return f"{y:04d}-{mth:02d}-{d:02d}"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)  # YYYY-MM-DD
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)  # DD/MM/YYYY
    if m:
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid(y, mth, d):
            return f"{y:04d}-{mth:02d}-{d:02d}"
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


def score_pair(x: dict, y: dict) -> tuple[int, list[str]]:
    # 1) Имя должно быть почти идентичным — иначе это разные гонки.
    sim = name_similarity(x["norm"], x["tokens"], y["norm"], y["tokens"])
    if sim < NAME_SIM_MIN:
        return 0, []

    # 2) Логика клиента: разные известные даты => разные издания, а не дубль.
    xd, yd = x["date"], y["date"]
    if xd and yd and xd != yd:
        return 0, []
    same_date = bool(xd) and xd == yd

    same_url = bool(x["website"]) and x["website"] == y["website"]
    dist = haversine_km(x["lat"], x["lon"], y["lat"], y["lon"])
    geo_close = dist is not None and dist <= GEO_MAX_KM

    # 3) Подтверждение: тот же URL или та же локация. Совпадение ТОЛЬКО по дате
    # принимаем лишь при идентичных нормализованных именах — иначе это разные
    # события одной серии в один праздничный день (напр. «Corrida da Liberdade»
    # 25 апреля в разных городах).
    identical_name = bool(x["tokens"]) and x["tokens"] == y["tokens"]
    if not (same_url or geo_close):
        if not (same_date and identical_name):
            return 0, []

    reasons = []
    score = sim * 50
    reasons.append(f"name~{int(sim * 100)}%")
    if same_date:
        score += 30
        reasons.append(f"same date={xd}")
    if same_url:
        score += 25
        reasons.append("same URL")
    if geo_close:
        score += 15
        reasons.append(f"geo~{dist:.1f}km")

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
    "GROUP", "RACE NAME", "STATUS", "DATE", "LOCATION",
    "SUGGESTED", "DECISION", "NOTES",
    "SCORE", "MATCH REASONS", "PRODUCT ID", "WEBSITE", "PERMALINK",
]
DECISION_OPTIONS = ["Keep", "Delete", "Not a duplicate"]


def _pick_keeper(indices, records):
    """Кого предлагаем оставить: приоритет опубликованному, затем меньший ID
    (более старый = каноничный, накопил ссылки/SEO)."""
    def sort_key(i):
        r = records[i]
        status_rank = 0 if r["status"] == "publish" else 1
        try:
            id_val = int(r["id"])
        except (TypeError, ValueError):
            id_val = 10 ** 12
        return (status_rank, id_val)

    return sorted(indices, key=sort_key)[0]


def build_report_rows(groups, records) -> list[list]:
    rows = [REPORT_HEADER]
    for gi, group in enumerate(groups, start=1):
        keeper = _pick_keeper(group["indices"], records)
        for idx in group["indices"]:
            r = records[idx]
            suggested = "Keep" if idx == keeper else "Delete"
            rows.append([
                gi,
                r["name"],
                r["status"],
                r["date"],
                r["location"],
                suggested,
                "",   # DECISION — заполняет клиент
                "",   # NOTES
                group["score"],
                ", ".join(group["reasons"]),
                r["id"],
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
    _apply_formatting(spreadsheet, ws, rows)
    logger.info("✅ Записано строк в отчёт: %d (групп-дублей: %d)", len(rows) - 1, max(int(rows[-1][0]) if len(rows) > 1 else 0, 0))


# Чередующиеся мягкие цвета фона для соседних групп (чтобы видеть, что с чем сравнивается).
_GROUP_COLORS = [
    {"red": 0.85, "green": 0.92, "blue": 1.00},   # голубой
    {"red": 0.87, "green": 0.95, "blue": 0.85},   # зелёный
    {"red": 1.00, "green": 0.95, "blue": 0.80},   # жёлтый
    {"red": 0.96, "green": 0.86, "blue": 0.90},   # розовый
]


def _apply_formatting(spreadsheet, ws, rows):
    sheet_id = ws.id
    ncols = len(REPORT_HEADER)
    requests = [
        # жирная шапка
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold",
        }},
        # заморозка шапки
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }},
    ]

    # выпадающий список в колонке DECISION
    dcol = REPORT_HEADER.index("DECISION")
    requests.append({"setDataValidation": {
        "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(rows),
                  "startColumnIndex": dcol, "endColumnIndex": dcol + 1},
        "rule": {
            "condition": {"type": "ONE_OF_LIST",
                          "values": [{"userEnteredValue": v} for v in DECISION_OPTIONS]},
            "showCustomUi": True, "strict": False,
        },
    }})

    # раскраска групп: соседние группы — разные цвета; строки одной группы идут подряд
    group_index = 0
    start = 1  # строка данных (0 — шапка)
    while start < len(rows):
        current_group = rows[start][0]
        end = start
        while end < len(rows) and rows[end][0] == current_group:
            end += 1
        color = _GROUP_COLORS[group_index % len(_GROUP_COLORS)]
        requests.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": start, "endRowIndex": end,
                      "startColumnIndex": 0, "endColumnIndex": ncols},
            "cell": {"userEnteredFormat": {"backgroundColor": color}},
            "fields": "userEnteredFormat.backgroundColor",
        }})
        group_index += 1
        start = end

    spreadsheet.batch_update({"requests": requests})
    logger.info("🎨 Применено форматирование: %d групп раскрашено, dropdown в DECISION", group_index)


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

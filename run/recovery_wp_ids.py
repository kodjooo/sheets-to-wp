from __future__ import annotations

import argparse
import csv
import html
import logging
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse


PRODUCT_ID_COLUMNS = ("WP PRODUCT ID EN", "WP PRODUCT ID PT")
VARIATION_ID_COLUMNS = ("WP VARIATION ID EN", "WP VARIATION ID PT")
VARIATION_DATA_COLUMNS = (
    "ATTRIBUTE",
    "VALUE",
    "DISTANCE",
    "TEAM",
    "TYPE",
    "LICENSE",
    "RACE START DATE",
    "RACE START TIME",
    "PRICE",
)
MAIN_STATUSES = {
    "published",
    "published (incomplete)",
    "revised (complete)",
    "revised (incomplete)",
}

TYPE_ALIASES = {
    "walking": "walking",
    "caminhada": "walking",
    "road running": "road-running",
    "road-running": "road-running",
    "corrida de estrada": "road-running",
    "corrida-de-estrada": "road-running",
    "half marathon": "half-marathon",
    "half-marathon": "half-marathon",
    "meia maratona": "half-marathon",
    "meia-maratona": "half-marathon",
    "kids race": "kids-race",
    "kids-race": "kids-race",
    "kids-race-pt": "kids-race",
    "wheelchair race": "wheelchair-race",
    "wheelchair-race": "wheelchair-race",
    "wheelchair-race-pt": "wheelchair-race",
}

ACF_FIELD_ALIASES = {
    "event_ticket_url": ("event_ticket_url",),
    "event_date_start": ("event_date_start", "event_start_date"),
    "event_location_text": ("event_location_text", "location_city"),
}


def is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def has_variation_data(row: dict[str, Any]) -> bool:
    return any(not is_missing(row.get(column)) for column in VARIATION_DATA_COLUMNS + VARIATION_ID_COLUMNS)


def extract_product_id_from_url(url: str | None) -> int | None:
    if not url:
        return None
    parsed = urlparse(html.unescape(str(url).strip()))
    query = parse_qs(parsed.query)
    for key in ("p", "post"):
        raw_values = query.get(key, [])
        for raw in raw_values:
            if str(raw).isdigit():
                return int(raw)
    match = re.search(r"/wp-json/wp/v2/product/(\d+)", parsed.path)
    if match:
        return int(match.group(1))
    return None


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(unquote(str(value).strip()))
    if not text:
        return ""
    parsed = urlparse(text if re.match(r"^[a-z]+://", text, re.I) else f"https://{text}")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/")
    query_pairs = []
    for key, values in sorted(parse_qs(parsed.query, keep_blank_values=True).items()):
        if key.lower().startswith(("utm_", "fbclid", "gclid")):
            continue
        for item in sorted(values):
            query_pairs.append((key, item))
    query = urlencode(query_pairs)
    return f"{host}{path}" + (f"?{query}" if query else "")


def slugify(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(str(value)).strip().lower()
    text = text.replace("_", "-").replace("/", " ")
    text = re.sub(r"-pt$", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9.\s-]+", "", text)
    return text.strip().replace(" ", "-")


def normalize_type(value: str | None) -> str:
    base = slugify(value).replace("-", " ")
    return TYPE_ALIASES.get(base, TYPE_ALIASES.get(slugify(value), slugify(value)))


def normalize_distance(value: str | None) -> str:
    if not value:
        return ""
    text = slugify(value).replace("-pt", "").replace("-", " ").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return slugify(value)
    number = match.group(1)
    if number == "21097":
        number = "21.097"
    try:
        dec = Decimal(number)
        number = str(dec.normalize()).replace("E+1", "0")
    except InvalidOperation:
        pass
    return f"{number} km"


def normalize_date(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"-pt$", "", str(value).strip(), flags=re.I)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            return ""
    return ""


def normalize_time(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"-pt$", "", str(value).strip(), flags=re.I)
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"
    match = re.fullmatch(r"(\d{1,2})(\d{2})", text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"
    return ""


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(str(value)).strip().lower()
    text = re.sub(r"[^a-z0-9\s-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _acf_fields(product: dict[str, Any] | None) -> dict[str, Any]:
    if not product:
        return {}
    acf = product.get("acf")
    if isinstance(acf, dict):
        return acf
    result = {}
    for item in product.get("meta_data", []) or []:
        key = item.get("key")
        if key:
            result[key] = item.get("value")
    return result


def get_acf_value(product: dict[str, Any] | None, canonical_key: str) -> Any:
    fields = _acf_fields(product)
    for key in ACF_FIELD_ALIASES.get(canonical_key, (canonical_key,)):
        if key in fields and fields[key] not in ("", None, []):
            return fields[key]
    return None


def product_categories(product: dict[str, Any] | None) -> set[str]:
    values = set()
    for category in (product or {}).get("categories", []) or []:
        values.add(slugify(category.get("name")))
        values.add(slugify(category.get("slug")))
    return {value for value in values if value}


def title_similarity(left: str | None, right: str | None) -> float:
    left_words = set(normalize_text(left).split())
    right_words = set(normalize_text(right).split())
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / len(left_words | right_words)


def _attribute_map(attributes: list[dict[str, Any]]) -> dict[str, str]:
    result = {}
    for attr in attributes or []:
        name = slugify(attr.get("name"))
        option = attr.get("option") or attr.get("value")
        if name:
            result[name] = str(option or "")
    return result


def _generic_attribute_value(attrs: dict[str, str]) -> str:
    known = {
        "type",
        "pa-type",
        "distance",
        "pa-distance",
        "team",
        "pa-team",
        "license",
        "pa-license",
        "race-start-date",
        "race-start-time",
    }
    for name, value in sorted(attrs.items()):
        if name not in known and value:
            return value
    return ""


def build_variation_key(row: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    attrs = _attribute_map(row.get("attributes", [])) if isinstance(row.get("attributes"), list) else {}
    type_value = row.get("TYPE") or attrs.get("type") or attrs.get("pa-type")
    distance_value = row.get("DISTANCE") or attrs.get("distance") or attrs.get("pa-distance")
    team_value = row.get("TEAM") or attrs.get("team") or attrs.get("pa-team")
    license_value = row.get("LICENSE") or attrs.get("license") or attrs.get("pa-license")
    date_value = row.get("RACE START DATE") or attrs.get("race-start-date")
    time_value = row.get("RACE START TIME") or attrs.get("race-start-time")
    value = row.get("VALUE") or attrs.get(slugify(row.get("ATTRIBUTE"))) or _generic_attribute_value(attrs)
    return tuple(
        sorted(
            {
                "type": normalize_type(type_value),
                "distance": normalize_distance(distance_value),
                "team": slugify(team_value),
                "license": slugify(license_value),
                "date": normalize_date(date_value),
                "time": normalize_time(time_value),
                "value": slugify(value),
            }.items()
        )
    )


def match_variations(sheet_rows: list[tuple[int, dict[str, Any]]], variations: list[dict[str, Any]]) -> tuple[dict[int, int], dict[int, str]]:
    wp_by_key = defaultdict(list)
    for variation in variations:
        wp_by_key[build_variation_key(variation)].append(variation.get("id"))
    sheet_keys = {row_index: build_variation_key(row) for row_index, row in sheet_rows}
    key_counts = Counter(sheet_keys.values())
    matches: dict[int, int] = {}
    failures: dict[int, str] = {}
    for row_index, key in sheet_keys.items():
        if key_counts[key] > 1:
            failures[row_index] = "ambiguous_variation_match"
            continue
        ids = [item for item in wp_by_key.get(key, []) if item]
        if len(ids) == 1:
            matches[row_index] = int(ids[0])
        elif len(ids) > 1:
            failures[row_index] = "ambiguous_variation_match"
        else:
            failures[row_index] = "no_variation_match"
    return matches, failures


@dataclass
class RecoveryResult:
    row_index: int
    race_name: str
    updates: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    variation_counts: dict[str, int] = field(default_factory=dict)
    matched_variations: dict[str, int] = field(default_factory=dict)
    ambiguous: bool = False


class WordPressRecoveryClient:
    def __init__(self, wp_url: str, consumer_key: str, consumer_secret: str, timeout: float = 20):
        self.wp_url = wp_url.rstrip("/")
        self.auth = (consumer_key, consumer_secret)
        self.timeout = timeout

    def get_html(self, url: str) -> str:
        import requests

        response = requests.get(url, timeout=self.timeout, headers={"User-Agent": "racefinder-recovery/1.0"})
        response.raise_for_status()
        return response.text

    def extract_product_id_from_html(self, html_text: str) -> int | None:
        patterns = [
            r'rel=["\']shortlink["\'][^>]+href=["\'][^"\']*[?&]p=(\d+)',
            r'href=["\'][^"\']*/wp-json/wp/v2/product/(\d+)',
            r'"@id"\s*:\s*"[^"]*/wp-json/wp/v2/product/(\d+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html_text, re.I)
            if match:
                return int(match.group(1))
        return None

    def find_hreflang_url(self, html_text: str, lang: str = "pt-pt") -> str | None:
        for tag_match in re.finditer(r"<link\b[^>]+>", html_text, re.I):
            tag = tag_match.group(0)
            if not re.search(r'rel=["\']alternate["\']', tag, re.I):
                continue
            if not re.search(rf'hreflang=["\']{re.escape(lang)}["\']', tag, re.I):
                continue
            href_match = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
            if href_match:
                return html.unescape(href_match.group(1))
        return None

    def get_product(self, product_id: int) -> dict[str, Any] | None:
        import requests

        response = requests.get(f"{self.wp_url}/wp-json/wc/v3/products/{product_id}", auth=self.auth, timeout=self.timeout)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def get_variations(self, product_id: int) -> list[dict[str, Any]]:
        import requests

        store_variations = self.get_store_api_variations(product_id)
        if store_variations and all(variation.get("attributes") for variation in store_variations):
            return store_variations

        result = []
        page = 1
        while True:
            response = requests.get(
                f"{self.wp_url}/wp-json/wc/v3/products/{product_id}/variations",
                auth=self.auth,
                params={"per_page": 100, "page": page},
                timeout=self.timeout,
            )
            response.raise_for_status()
            batch = response.json() or []
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1

    def get_store_api_variations(self, product_id: int) -> list[dict[str, Any]]:
        import requests

        response = requests.get(
            f"{self.wp_url}/wp-json/wc/store/v1/products/{product_id}",
            timeout=self.timeout,
            headers={"User-Agent": "racefinder-recovery/1.0"},
        )
        if response.status_code >= 400:
            return []
        product = response.json() or {}
        variations = product.get("variations") or []
        result = []
        for variation in variations:
            variation_id = variation.get("id")
            if not variation_id:
                continue
            attrs = []
            for attr in variation.get("attributes", []) or []:
                attrs.append(
                    {
                        "name": attr.get("name") or attr.get("attribute"),
                        "option": attr.get("value") or attr.get("term") or attr.get("option"),
                    }
                )
            result.append({"id": variation_id, "attributes": attrs})
        return result

    def search_products(self, search: str) -> list[dict[str, Any]]:
        import requests

        if not search:
            return []
        response = requests.get(
            f"{self.wp_url}/wp-json/wc/v3/products",
            auth=self.auth,
            params={"search": search, "per_page": 20},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json() or []

    def iter_products(self, search: str | None = None, max_pages: int = 10) -> list[dict[str, Any]]:
        import requests

        result = []
        for page in range(1, max_pages + 1):
            params = {"per_page": 100, "page": page, "status": "publish"}
            if search:
                params["search"] = search
            response = requests.get(
                f"{self.wp_url}/wp-json/wc/v3/products",
                auth=self.auth,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            batch = response.json() or []
            result.extend(batch)
            if len(batch) < 100:
                break
        return result

    def validate_product(self, product: dict[str, Any] | None, row: dict[str, Any]) -> bool:
        if not product or product.get("type") not in ("variable", "simple", "external"):
            return False
        website = normalize_url(row.get("WEBSITE"))
        ticket_url = normalize_url(get_acf_value(product, "event_ticket_url"))
        if website and ticket_url and website != ticket_url:
            return False
        expected_date = normalize_date(row.get("EVENT START DATE"))
        product_date = normalize_date(get_acf_value(product, "event_date_start"))
        if expected_date and product_date and expected_date != product_date:
            return False
        return True

    def product_match_score(self, product: dict[str, Any], row: dict[str, Any]) -> tuple[int, list[str]]:
        reasons = []
        score = 0
        website = normalize_url(row.get("WEBSITE"))
        ticket_url = normalize_url(get_acf_value(product, "event_ticket_url"))
        if website and ticket_url:
            if website != ticket_url:
                return 0, ["website_mismatch"]
            score += 5
            reasons.append("website_match")
        expected_date = normalize_date(row.get("EVENT START DATE"))
        product_date = normalize_date(get_acf_value(product, "event_date_start"))
        if expected_date and product_date:
            if expected_date != product_date:
                return 0, ["date_mismatch"]
            score += 3
            reasons.append("date_match")
        expected_city = normalize_text(row.get("LOCATION (CITY)"))
        product_city = normalize_text(get_acf_value(product, "event_location_text"))
        if expected_city and product_city and expected_city in product_city:
            score += 1
            reasons.append("city_match")
        expected_categories = {slugify(row.get("CATEGORY")), slugify(row.get("SUBCATEGORY"))} - {""}
        if expected_categories and expected_categories & product_categories(product):
            score += 1
            reasons.append("category_match")
        title_score = max(
            title_similarity(row.get("RACE NAME"), product.get("name")),
            title_similarity(row.get("RACE NAME (PT)"), product.get("name")),
        )
        if title_score >= 0.5:
            score += 1
            reasons.append("title_match")
        return score, reasons


class RecoveryRunner:
    def __init__(self, wp_client: WordPressRecoveryClient, logger: logging.Logger | None = None):
        self.wp = wp_client
        self.logger = logger or logging.getLogger(__name__)

    def recover_product_ids(self, row: dict[str, Any]) -> tuple[dict[str, int], dict[str, str], list[str]]:
        found: dict[str, int] = {}
        sources: dict[str, str] = {}
        reasons: list[str] = []
        if not is_missing(row.get("WP PRODUCT ID EN")):
            found["WP PRODUCT ID EN"] = int(float(row["WP PRODUCT ID EN"]))
            sources["WP PRODUCT ID EN"] = "sheet_existing"
        direct_id = extract_product_id_from_url(row.get("LINK RACEFINDER"))
        if not found.get("WP PRODUCT ID EN") and not direct_id and row.get("LINK RACEFINDER"):
            try:
                direct_id = self.wp.extract_product_id_from_html(self.wp.get_html(str(row.get("LINK RACEFINDER"))))
                if direct_id:
                    sources["WP PRODUCT ID EN"] = "public_page"
            except Exception as exc:
                self.logger.warning("Не удалось извлечь ID из публичной страницы LINK RACEFINDER: %s", exc)
        if not found.get("WP PRODUCT ID EN") and direct_id:
            product = self.wp.get_product(direct_id)
            if self.wp.validate_product(product, row):
                found["WP PRODUCT ID EN"] = direct_id
                sources.setdefault("WP PRODUCT ID EN", "link_racefinder")
            else:
                reasons.append("validation_failed")
        if not found.get("WP PRODUCT ID EN"):
            product_id, source, reason = self.find_product_by_fallbacks(row, preferred_lang="EN")
            if product_id:
                found["WP PRODUCT ID EN"] = product_id
                sources["WP PRODUCT ID EN"] = source
            elif reason:
                reasons.append(reason)
        if not found.get("WP PRODUCT ID EN") and not reasons:
            reasons.append("no_product_match")
        if found.get("WP PRODUCT ID EN") and not found.get("WP PRODUCT ID PT"):
            existing_pt = row.get("WP PRODUCT ID PT")
            if not is_missing(existing_pt):
                found["WP PRODUCT ID PT"] = int(float(existing_pt))
                sources["WP PRODUCT ID PT"] = "sheet_existing"
        if found.get("WP PRODUCT ID EN") and not found.get("WP PRODUCT ID PT"):
            product = self.wp.get_product(found["WP PRODUCT ID EN"])
            permalink = product.get("permalink") if product else None
            if permalink:
                en_html = self.wp.get_html(permalink)
                pt_url = self.wp.find_hreflang_url(en_html)
                if pt_url:
                    pt_html = self.wp.get_html(pt_url)
                    pt_id = extract_product_id_from_url(pt_url) or self.wp.extract_product_id_from_html(pt_html)
                    if pt_id and self.wp.validate_product(self.wp.get_product(pt_id), row):
                        found["WP PRODUCT ID PT"] = pt_id
                        sources["WP PRODUCT ID PT"] = "hreflang_pt"
                    else:
                        reasons.append("pt_translation_not_found")
        if found.get("WP PRODUCT ID EN") and not found.get("WP PRODUCT ID PT"):
            product_id, source, reason = self.find_product_by_fallbacks(row, preferred_lang="PT", exclude_ids={found["WP PRODUCT ID EN"]})
            if product_id:
                found["WP PRODUCT ID PT"] = product_id
                sources["WP PRODUCT ID PT"] = source
            elif reason:
                reasons.append(reason if reason == "ambiguous_product_match" else "pt_translation_not_found")
        return found, sources, reasons

    def find_product_by_fallbacks(self, row: dict[str, Any], preferred_lang: str, exclude_ids: set[int] | None = None) -> tuple[int | None, str, str]:
        exclude_ids = exclude_ids or set()
        search_terms = []
        if row.get("WEBSITE"):
            search_terms.append(str(row["WEBSITE"]))
        if preferred_lang == "PT" and row.get("RACE NAME (PT)"):
            search_terms.append(str(row["RACE NAME (PT)"]))
        if row.get("RACE NAME"):
            search_terms.append(str(row["RACE NAME"]))

        candidates_by_id: dict[int, dict[str, Any]] = {}
        for term in search_terms:
            for product in self.wp.search_products(term):
                if product.get("id") and int(product["id"]) not in exclude_ids:
                    candidates_by_id[int(product["id"])] = product

        if row.get("WEBSITE"):
            max_pages = int(os.getenv("RECOVERY_WP_IDS_PRODUCT_SCAN_PAGES", "10") or "10")
            for product in self.wp.iter_products(max_pages=max_pages):
                product_id = product.get("id")
                if product_id and int(product_id) not in exclude_ids:
                    candidates_by_id[int(product_id)] = product

        scored = []
        for product_id, product in candidates_by_id.items():
            if not self.wp.validate_product(product, row):
                continue
            score, score_reasons = self.wp.product_match_score(product, row)
            if score > 0:
                scored.append((score, product_id, score_reasons))

        if not scored:
            return None, "", "no_product_match"
        scored.sort(reverse=True)
        best_score = scored[0][0]
        best = [item for item in scored if item[0] == best_score]
        if len(best) > 1:
            return None, "", "ambiguous_product_match"
        if best_score < 4:
            return None, "", "validation_failed"
        source = "website_acf" if "website_match" in best[0][2] else "composite_key"
        return best[0][1], source, ""

    def recover_row(self, row_index: int, row: dict[str, Any], child_rows: list[tuple[int, dict[str, Any]]]) -> RecoveryResult:
        result = RecoveryResult(row_index=row_index, race_name=str(row.get("RACE NAME") or row.get("RACE NAME (PT)") or ""))
        product_ids, sources, reasons = self.recover_product_ids(row)
        result.sources.update(sources)
        result.reasons.extend(reasons)
        for column, value in product_ids.items():
            if is_missing(row.get(column)):
                result.updates[column] = value
        for lang, product_column, variation_column in (
            ("EN", "WP PRODUCT ID EN", "WP VARIATION ID EN"),
            ("PT", "WP PRODUCT ID PT", "WP VARIATION ID PT"),
        ):
            product_id = product_ids.get(product_column) or (None if is_missing(row.get(product_column)) else int(float(row[product_column])))
            if not product_id:
                continue
            variations = self.wp.get_variations(product_id)
            result.variation_counts[lang] = len(variations)
            missing_children = [(idx, item) for idx, item in child_rows if is_missing(item.get(variation_column))]
            matches, failures = match_variations(missing_children, variations)
            result.matched_variations[lang] = len(matches)
            for child_index, variation_id in matches.items():
                result.updates[f"{variation_column}:{child_index}"] = variation_id
            for reason in failures.values():
                result.reasons.append(f"{lang.lower()}_{reason}")
        result.ambiguous = any("ambiguous" in reason for reason in result.reasons)
        return result


def group_events(rows: list[tuple[int, dict[str, Any]]]) -> list[tuple[int, dict[str, Any], list[tuple[int, dict[str, Any]]]]]:
    groups = []
    current = None
    children: list[tuple[int, dict[str, Any]]] = []
    for row_index, row in rows:
        status = str(row.get("STATUS", "")).strip().lower()
        if status in MAIN_STATUSES:
            if current:
                groups.append((*current, children))
            current = (row_index, row)
            children = []
        elif current:
            children.append((row_index, row))
    if current:
        groups.append((*current, children))
    return groups


def needs_recovery(row: dict[str, Any], children: list[tuple[int, dict[str, Any]]]) -> bool:
    if any(is_missing(row.get(column)) for column in PRODUCT_ID_COLUMNS):
        return True
    variation_rows = [(0, row)] + [(idx, child) for idx, child in children if has_variation_data(child)]
    return any(any(is_missing(item.get(column)) for column in VARIATION_ID_COLUMNS) for _, item in variation_rows)


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Восстановление WP product/variation ID из опубликованных карточек.")
    parser.add_argument("--mode", choices=("dry-run", "apply"), default=os.getenv("RECOVERY_WP_IDS_MODE", "dry-run"))
    parser.add_argument("--limit", type=int, default=int(os.getenv("RECOVERY_WP_IDS_LIMIT", "0") or "0"))
    parser.add_argument("--report", default=os.getenv("RECOVERY_WP_IDS_REPORT", ""))
    return parser.parse_args(argv)


def write_report(path: str, rows: list[RecoveryResult], mode: str) -> None:
    if not path:
        return
    with open(path, "w", encoding="utf-8", newline="") as report_file:
        writer = csv.DictWriter(
            report_file,
            fieldnames=[
                "mode",
                "row_index",
                "race_name",
                "updates",
                "sources",
                "variation_counts",
                "matched_variations",
                "reasons",
                "ambiguous",
            ],
        )
        writer.writeheader()
        for result in rows:
            writer.writerow(
                {
                    "mode": mode,
                    "row_index": result.row_index,
                    "race_name": result.race_name,
                    "updates": result.updates,
                    "sources": result.sources,
                    "variation_counts": result.variation_counts,
                    "matched_variations": result.matched_variations,
                    "reasons": result.reasons,
                    "ambiguous": result.ambiguous,
                }
            )


def main(argv: list[str] | None = None) -> int:
    from _1_google_loader import load_all_rows, load_config, update_cell

    args = parse_args(argv)
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(message)s")
    config = load_config()
    rows, headers = load_all_rows()
    client = WordPressRecoveryClient(config["wp_url"], config["consumer_key"], config["consumer_secret"], float(config.get("wcapi_timeout_sec", 20)))
    runner = RecoveryRunner(client)
    processed = product_updates = variation_updates = manual = 0
    report_rows: list[RecoveryResult] = []
    for row_index, row, children in group_events(rows):
        if not needs_recovery(row, children):
            continue
        if args.limit and processed >= args.limit:
            break
        processed += 1
        variation_rows = [(row_index, row)] + [(idx, child) for idx, child in children if has_variation_data(child)]
        result = runner.recover_row(row_index, row, variation_rows)
        report_rows.append(result)
        product_updates += len([key for key in result.updates if ":" not in key])
        variation_updates += len([key for key in result.updates if ":" in key])
        if result.ambiguous or result.reasons:
            manual += 1
        logging.info(
            "Recovery row=%s race=%s updates=%s sources=%s reasons=%s mode=%s",
            row_index,
            result.race_name,
            result.updates,
            result.sources,
            result.reasons,
            args.mode,
        )
        if args.mode == "apply" and not result.ambiguous:
            for key, value in result.updates.items():
                if ":" in key:
                    column, child_index = key.split(":", 1)
                    update_cell(int(child_index), column, value, headers)
                else:
                    update_cell(row_index, key, value, headers)
    logging.info("Recovery summary processed=%s product_ids=%s variation_ids=%s manual_review=%s", processed, product_updates, variation_updates, manual)
    write_report(args.report, report_rows, args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

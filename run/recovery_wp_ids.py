from __future__ import annotations

import argparse
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


def is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == ""


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


def _attribute_map(attributes: list[dict[str, Any]]) -> dict[str, str]:
    result = {}
    for attr in attributes or []:
        name = slugify(attr.get("name"))
        option = attr.get("option") or attr.get("value")
        if name:
            result[name] = str(option or "")
    return result


def build_variation_key(row: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    attrs = _attribute_map(row.get("attributes", [])) if isinstance(row.get("attributes"), list) else {}
    type_value = row.get("TYPE") or attrs.get("type") or attrs.get("pa-type") or row.get("ATTRIBUTE")
    distance_value = row.get("DISTANCE") or attrs.get("distance") or attrs.get("pa-distance")
    team_value = row.get("TEAM") or attrs.get("team") or attrs.get("pa-team")
    license_value = row.get("LICENSE") or attrs.get("license") or attrs.get("pa-license")
    date_value = row.get("RACE START DATE") or attrs.get("race-start-date")
    time_value = row.get("RACE START TIME") or attrs.get("race-start-time")
    value = row.get("VALUE") or attrs.get(slugify(row.get("ATTRIBUTE")))
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

    def validate_product(self, product: dict[str, Any] | None, row: dict[str, Any]) -> bool:
        if not product or product.get("type") not in ("variable", "simple", "external"):
            return False
        website = normalize_url(row.get("WEBSITE"))
        meta_values = [normalize_url(item.get("value")) for item in product.get("meta_data", []) if item.get("key") == "event_ticket_url"]
        if website and meta_values and website not in meta_values:
            return False
        return True


class RecoveryRunner:
    def __init__(self, wp_client: WordPressRecoveryClient, logger: logging.Logger | None = None):
        self.wp = wp_client
        self.logger = logger or logging.getLogger(__name__)

    def recover_product_ids(self, row: dict[str, Any]) -> tuple[dict[str, int], dict[str, str], list[str]]:
        found: dict[str, int] = {}
        sources: dict[str, str] = {}
        reasons: list[str] = []
        direct_id = extract_product_id_from_url(row.get("LINK RACEFINDER"))
        if not direct_id and row.get("LINK RACEFINDER"):
            try:
                direct_id = self.wp.extract_product_id_from_html(self.wp.get_html(str(row.get("LINK RACEFINDER"))))
                if direct_id:
                    sources["WP PRODUCT ID EN"] = "public_page"
            except Exception as exc:
                self.logger.warning("Не удалось извлечь ID из публичной страницы LINK RACEFINDER: %s", exc)
        if direct_id:
            product = self.wp.get_product(direct_id)
            if self.wp.validate_product(product, row):
                found["WP PRODUCT ID EN"] = direct_id
                sources.setdefault("WP PRODUCT ID EN", "link_racefinder")
            else:
                reasons.append("validation_failed")
        if not found.get("WP PRODUCT ID EN"):
            candidates = []
            for search_value in (row.get("WEBSITE"), row.get("RACE NAME")):
                if not search_value:
                    continue
                candidates.extend(self.wp.search_products(str(search_value)))
            valid = [item for item in candidates if self.wp.validate_product(item, row)]
            unique = {int(item["id"]): item for item in valid if item.get("id")}
            if len(unique) == 1:
                found["WP PRODUCT ID EN"] = next(iter(unique))
                sources["WP PRODUCT ID EN"] = "validated_search"
            elif len(unique) > 1:
                reasons.append("ambiguous_product_match")
        if found.get("WP PRODUCT ID EN"):
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
            pt_search = row.get("RACE NAME (PT)") or row.get("RACE NAME")
            valid_pt = [item for item in self.wp.search_products(str(pt_search or "")) if self.wp.validate_product(item, row)]
            unique_pt = {int(item["id"]): item for item in valid_pt if item.get("id") and int(item["id"]) != found["WP PRODUCT ID EN"]}
            if len(unique_pt) == 1:
                found["WP PRODUCT ID PT"] = next(iter(unique_pt))
                sources["WP PRODUCT ID PT"] = "validated_pt_search"
            elif len(unique_pt) > 1:
                reasons.append("ambiguous_product_match")
        return found, sources, reasons

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
            missing_children = [(idx, item) for idx, item in child_rows if is_missing(item.get(variation_column))]
            matches, failures = match_variations(missing_children, variations)
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
    return any(any(is_missing(child.get(column)) for column in VARIATION_ID_COLUMNS) for _, child in children)


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Восстановление WP product/variation ID из опубликованных карточек.")
    parser.add_argument("--mode", choices=("dry-run", "apply"), default=os.getenv("RECOVERY_WP_IDS_MODE", "dry-run"))
    parser.add_argument("--limit", type=int, default=int(os.getenv("RECOVERY_WP_IDS_LIMIT", "0") or "0"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from _1_google_loader import load_all_rows, load_config, update_cell

    args = parse_args(argv)
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(message)s")
    config = load_config()
    rows, headers = load_all_rows()
    client = WordPressRecoveryClient(config["wp_url"], config["consumer_key"], config["consumer_secret"], float(config.get("wcapi_timeout_sec", 20)))
    runner = RecoveryRunner(client)
    processed = product_updates = variation_updates = manual = 0
    for row_index, row, children in group_events(rows):
        if not needs_recovery(row, children):
            continue
        if args.limit and processed >= args.limit:
            break
        processed += 1
        result = runner.recover_row(row_index, row, children)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import json
from collections import defaultdict
import logging
from pathlib import Path
import time

import requests

from _1_google_loader import load_config
from recovery_wp_ids import TYPE_ALIASES, slugify


class DSU:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            return x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def fetch_attributes(base_url: str, auth: tuple[str, str], timeout: float) -> list[dict]:
    response = requests.get(f"{base_url}/wp-json/wc/v3/products/attributes", auth=auth, timeout=timeout)
    response.raise_for_status()
    return response.json() or []


def fetch_terms(
    base_url: str,
    auth: tuple[str, str],
    timeout: float,
    attr_id: int,
    per_page: int = 100,
    max_pages_per_attr: int = 200,
) -> list[dict]:
    page = 1
    result = []
    failed_pages: list[int] = []
    while page <= max_pages_per_attr:
        try:
            response = requests.get(
                f"{base_url}/wp-json/wc/v3/products/attributes/{attr_id}/terms",
                auth=auth,
                params={"per_page": per_page, "page": page, "lang": "all"},
                timeout=timeout,
            )
            response.raise_for_status()
            batch = response.json() or []
            result.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        except Exception as exc:
            logging.warning("Skip terms page attr_id=%s page=%s: %s", attr_id, page, exc)
            failed_pages.append(page)
            page += 1
            continue

    # Retry failed pages a few times; keeps long runs resilient to transient DNS issues.
    retries = 3
    for failed in list(failed_pages):
        recovered = False
        for attempt in range(1, retries + 1):
            try:
                time.sleep(1.5 * attempt)
                response = requests.get(
                    f"{base_url}/wp-json/wc/v3/products/attributes/{attr_id}/terms",
                    auth=auth,
                    params={"per_page": per_page, "page": failed, "lang": "all"},
                    timeout=timeout,
                )
                response.raise_for_status()
                batch = response.json() or []
                result.extend(batch)
                recovered = True
                logging.info("Recovered terms page attr_id=%s page=%s on retry=%s", attr_id, failed, attempt)
                break
            except Exception as exc:
                logging.warning("Retry failed attr_id=%s page=%s attempt=%s: %s", attr_id, failed, attempt, exc)
        if not recovered:
            logging.error("Unrecovered terms page attr_id=%s page=%s", attr_id, failed)
    return result


def canonical_type(value: str) -> str:
    norm = slugify(value).replace("-", " ")
    return TYPE_ALIASES.get(norm, TYPE_ALIASES.get(slugify(value), ""))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cfg = load_config()
    base_url = cfg["wp_url"].rstrip("/")
    timeout = float(cfg.get("wcapi_timeout_sec", 20))
    per_page = int(cfg.get("translation_aliases_per_page", 100))
    max_pages_per_attr = int(cfg.get("translation_aliases_max_pages_per_attr", 200))
    auth = (cfg["consumer_key"], cfg["consumer_secret"])

    attributes = fetch_attributes(base_url, auth, timeout)
    logging.info("Attributes found: %s", len(attributes))
    type_aliases: dict[str, str] = {}
    attribute_name_aliases: dict[str, str] = {}
    value_candidates: dict[str, set[str]] = defaultdict(set)
    dsu = DSU()

    coverage: dict[str, dict[str, int | str]] = {}
    for idx, attribute in enumerate(attributes, start=1):
        attr_id = attribute.get("id")
        attr_name = str(attribute.get("name") or "")
        attr_slug = slugify(attribute.get("slug") or attr_name)
        if not attr_id:
            continue
        canonical_attr = attr_slug.replace("pa-", "")
        attribute_name_aliases[attr_slug] = canonical_attr
        if attr_name:
            attribute_name_aliases[slugify(attr_name)] = canonical_attr
        logging.info("Loading terms %s/%s attr_id=%s slug=%s", idx, len(attributes), attr_id, attr_slug)
        terms = fetch_terms(
            base_url,
            auth,
            timeout,
            int(attr_id),
            per_page=per_page,
            max_pages_per_attr=max_pages_per_attr,
        )
        logging.info("Loaded terms attr_id=%s count=%s", attr_id, len(terms))
        coverage[attr_slug] = {"attr_id": int(attr_id), "terms_loaded": len(terms)}
        by_id = {int(term["id"]): term for term in terms if term.get("id")}

        for term in terms:
            if str(term.get("lang", "")).lower() != "pt":
                continue
            translations = term.get("translations") or {}
            en_id = translations.get("en")
            pt_id = term.get("id")
            if not en_id or not pt_id:
                continue
            try:
                en_term = by_id.get(int(en_id))
            except (TypeError, ValueError):
                en_term = None
            if not en_term:
                continue

            pt_name = str(term.get("name") or "")
            en_name = str(en_term.get("name") or "")
            pt_slug = slugify(term.get("slug") or pt_name)
            en_slug = slugify(en_term.get("slug") or en_name)
            if not pt_slug or not en_slug:
                continue

            # Build bidirectional equivalence groups for all translated terms.
            dsu.union(pt_slug, en_slug)

            # Type aliases: only terms that map to known canonical type names.
            en_type = canonical_type(en_name) or canonical_type(en_slug)
            if en_type:
                type_aliases[pt_slug] = en_type
                continue

            # Generic value aliases for known selector-like attributes.
            if attr_slug in {"pa-running", "running", "pa-cycling", "cycling", "pa-type", "type"}:
                value_candidates[pt_slug].add(en_slug)

    value_aliases = {pt: sorted(values)[0] for pt, values in sorted(value_candidates.items()) if len(values) == 1}
    groups_by_root: dict[str, set[str]] = defaultdict(set)
    for term in list(dsu.parent.keys()):
        groups_by_root[dsu.find(term)].add(term)
    equivalence_groups = [sorted(group) for group in groups_by_root.values() if len(group) > 1]
    payload = {
        "type_aliases": dict(sorted(type_aliases.items())),
        "value_aliases": value_aliases,
        "attribute_name_aliases": dict(sorted(attribute_name_aliases.items())),
        "equivalence_groups": sorted(equivalence_groups, key=lambda g: (len(g), g)),
        "coverage": coverage,
    }
    logging.info("Built aliases: type=%s value=%s", len(payload["type_aliases"]), len(payload["value_aliases"]))

    output_path = Path(cfg.get("translation_aliases_output_path", "/tmp/translation_aliases.json"))
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=True, indent=2, sort_keys=True)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

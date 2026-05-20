def normalize_attribute_name(name: str) -> str:
    return str(name or "").strip()


def merge_attribute_map_case_insensitive(raw_attributes: dict) -> dict:
    merged = {}
    key_by_fold = {}

    for raw_key, raw_value in (raw_attributes or {}).items():
        key_norm = normalize_attribute_name(raw_key)
        if not key_norm:
            continue
        fold_key = key_norm.casefold()
        canonical_key = key_by_fold.get(fold_key)
        if canonical_key is None:
            canonical_key = key_norm
            key_by_fold[fold_key] = canonical_key
            merged[canonical_key] = []

        if isinstance(raw_value, list):
            values = [str(item).strip() for item in raw_value if str(item).strip()]
        elif raw_value in (None, ""):
            values = []
        else:
            value_norm = str(raw_value).strip()
            values = [value_norm] if value_norm else []

        for value in values:
            if value not in merged[canonical_key]:
                merged[canonical_key].append(value)

    return merged


def normalize_attribute_payload(raw_attributes: dict) -> dict:
    return merge_attribute_map_case_insensitive(raw_attributes)


def select_attribute_id(attributes: list, name: str):
    normalized_name = str(name).strip().lower()
    normalized_slug = normalized_name.replace(" ", "-")
    normalized_slug_with_prefix = f"pa_{normalized_slug}"

    def _id_from(attr):
        return attr.get("id")

    slug_matches = [
        attr for attr in attributes
        if str(attr.get("slug", "")).strip().lower() in {normalized_slug, normalized_slug_with_prefix}
        and _id_from(attr) is not None
    ]
    if len(slug_matches) == 1:
        return _id_from(slug_matches[0])
    if len(slug_matches) > 1:
        ids = [_id_from(attr) for attr in slug_matches]
        raise RuntimeError(
            f"Найдено несколько атрибутов по slug '{normalized_slug}' для '{name}': {ids}"
        )

    name_matches = [
        attr for attr in attributes
        if str(attr.get("name", "")).strip().lower() == normalized_name and _id_from(attr) is not None
    ]
    if len(name_matches) == 1:
        return _id_from(name_matches[0])
    if len(name_matches) > 1:
        ids = [_id_from(attr) for attr in name_matches]
        raise RuntimeError(
            f"Найдено несколько атрибутов по name '{normalized_name}' для '{name}': {ids}"
        )

    return None


def get_missing_pt_fields(result: dict) -> list[str]:
    if not isinstance(result, dict):
        return []
    missing = []

    def _has_text(value) -> bool:
        return isinstance(value, str) and value.strip() != ""

    def _has_list(value) -> bool:
        return isinstance(value, list) and len(value) > 0

    pairs = [
        ("summary", "summary_pt"),
        ("org_info", "org_info_pt"),
        ("faq", "faq_pt"),
    ]
    for en_key, pt_key in pairs:
        if _has_text(result.get(en_key, "")) and not _has_text(result.get(pt_key, "")):
            missing.append(pt_key)

    benefits_en = result.get("benefits", [])
    benefits_pt = result.get("benefits_pt", [])
    if _has_list(benefits_en) and not _has_list(benefits_pt):
        missing.append("benefits_pt")

    return missing


def parse_subcategory_values(raw_value):
    # Нормализуем список подкатегорий из строки/списка, разделитель — запятая.
    if raw_value is None:
        return []
    if isinstance(raw_value, (list, tuple, set)):
        values = []
        for item in raw_value:
            values.extend(parse_subcategory_values(item))
        return [value for value in values if value]
    if isinstance(raw_value, str):
        parts = [part.strip() for part in raw_value.split(",")]
        return [part for part in parts if part]
    value = str(raw_value).strip()
    return [value] if value else []


def normalize_category_pairs(raw_pairs):
    # Разворачиваем пары (CATEGORY, SUBCATEGORY), поддерживаем несколько подкатегорий через запятую.
    normalized = []
    seen = set()
    for item in raw_pairs:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        category_name, subcategory_name = item
        if not category_name:
            continue
        subcategories = parse_subcategory_values(subcategory_name)
        if subcategories:
            for subcategory in subcategories:
                key = (category_name, subcategory)
                if key not in seen:
                    normalized.append(key)
                    seen.add(key)
        else:
            key = (category_name, None)
            if key not in seen:
                normalized.append(key)
                seen.add(key)
    return normalized


def parse_faq_items(raw_faq: str):
    # Разбираем FAQ вида "Q: ... / A: ..." в формат ACF repeater.
    if not isinstance(raw_faq, str) or not raw_faq.strip():
        return []

    items = []
    pending_question = None

    for raw_line in raw_faq.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("<strong>faq"):
            continue
        if line.startswith("•"):
            line = line[1:].strip()

        lower = line.lower()
        if lower.startswith("q:"):
            pending_question = line[2:].strip()
            continue
        if lower.startswith("a:"):
            answer = line[2:].strip()
            if pending_question:
                items.append(
                    {
                        "item_title": pending_question,
                        "item_description": answer,
                    }
                )
                pending_question = None

    return items

def normalize_attribute_payload(raw_attributes: dict) -> dict:
    normalized = {}
    for key, value in raw_attributes.items():
        if isinstance(value, list):
            normalized[key] = value
        elif value in (None, ""):
            normalized[key] = []
        else:
            normalized[key] = [value]
    return normalized


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

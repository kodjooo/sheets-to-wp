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

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

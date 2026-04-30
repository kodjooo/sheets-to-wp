from woocommerce import API
import json
import logging
import time

from _1_google_loader import load_config
config = load_config()

wcapi = API(
    url=config["wp_url"],
    consumer_key=config["consumer_key"],
    consumer_secret=config["consumer_secret"],
    version="wc/v3",
    timeout=float(config.get("wcapi_timeout_sec", 20))
)

def _wcapi_request_with_retry(method: str, endpoint: str, payload: dict | None = None):
    max_attempts = int(config.get("wcapi_max_attempts", 4))
    base_delay = float(config.get("wcapi_base_delay_sec", 1.5))
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            if method == "GET":
                return wcapi.get(endpoint)
            if method == "POST":
                return wcapi.post(endpoint, payload)
            if method == "PUT":
                return wcapi.put(endpoint, payload)
            if method == "DELETE":
                return wcapi.delete(endpoint, params=payload or {})
            raise ValueError(f"Неизвестный метод запроса: {method}")
        except Exception as exc:
            last_err = exc
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logging.warning(
                    "⚠️ Ошибка запроса WooCommerce %s %s (попытка %s/%s): %s",
                    method,
                    endpoint,
                    attempt,
                    max_attempts,
                    exc
                )
                logging.info("⏳ Повтор через %.1f сек...", delay)
                time.sleep(delay)
    raise last_err


def _as_int(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _norm_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _load_all_variations(product_id):
    items = []
    page = 1
    while True:
        endpoint = f"products/{product_id}/variations?per_page=100&page={page}"
        response = _wcapi_request_with_retry("GET", endpoint)
        response.raise_for_status()
        batch = response.json() or []
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return items


def _build_product_attr_map(product_id):
    response = _wcapi_request_with_retry("GET", f"products/{product_id}")
    response.raise_for_status()
    product = response.json() or {}
    product_attributes = product.get("attributes", [])
    return {
        _norm_text(attr.get("name")): attr["id"]
        for attr in product_attributes
        if "id" in attr and _norm_text(attr.get("name"))
    }


def _build_payload(entry, attr_name_to_id):
    attrs_for_api = []
    for attr in entry.get("attributes", []):
        name = _norm_text(attr.get("name"))
        option = _norm_text(attr.get("option"))
        if not name or not option:
            continue
        attr_id = attr_name_to_id.get(name)
        if not attr_id:
            logging.warning("⚠️ Атрибут '%s' не найден у продукта, пропускаем в вариации.", name)
            continue
        attrs_for_api.append({"id": attr_id, "option": option})
    return {
        "regular_price": str(entry.get("regular_price", "0")),
        "attributes": attrs_for_api,
    }


def _normalize_payload(payload):
    attrs = payload.get("attributes", [])
    attrs_norm = sorted(
        (int(attr.get("id", 0)), _norm_text(attr.get("option")))
        for attr in attrs
        if attr.get("id")
    )
    return {
        "regular_price": _norm_text(payload.get("regular_price")),
        "attributes": attrs_norm,
    }


def _normalize_existing_variation(variation):
    attrs = []
    for attr in variation.get("attributes", []):
        attr_id = _as_int(attr.get("id"))
        if not attr_id:
            continue
        attrs.append((attr_id, _norm_text(attr.get("option"))))
    return {
        "regular_price": _norm_text(variation.get("regular_price")),
        "attributes": sorted(attrs),
    }


def sync_variations_by_ids(product_id, variation_entries):
    """
    Полная синхронизация вариаций продукта:
    - update существующих по existing_variation_id,
    - create для отсутствующих,
    - delete всех лишних в WP.

    variation_entries: список dict:
    {
      "row_index": int,
      "existing_variation_id": str|int|None,
      "regular_price": str,
      "attributes": [{"name": "...", "option": "..."}]
    }
    """
    attr_name_to_id = _build_product_attr_map(product_id)
    existing_variations = _load_all_variations(product_id)
    existing_by_id = {
        int(v["id"]): v
        for v in existing_variations
        if v.get("id") is not None
    }
    existing_norm_to_ids = {}
    for variation_id, variation in existing_by_id.items():
        norm = _normalize_existing_variation(variation)
        existing_norm_to_ids.setdefault(
            (norm["regular_price"], tuple(norm["attributes"])),
            []
        ).append(variation_id)

    row_to_variation_id = {}
    kept_ids = set()

    for entry in variation_entries:
        row_index = entry.get("row_index")
        payload = _build_payload(entry, attr_name_to_id)
        desired_norm = _normalize_payload(payload)
        desired_key = (desired_norm["regular_price"], tuple(desired_norm["attributes"]))
        existing_id = _as_int(entry.get("existing_variation_id"))

        # Сначала пытаемся использовать ID из таблицы, но только если он реально соответствует текущей записи.
        if existing_id and existing_id in existing_by_id and existing_id not in kept_ids:
            current_norm = _normalize_existing_variation(existing_by_id[existing_id])
            if current_norm == desired_norm:
                final_id = existing_id
            else:
                # Если ID в таблице не соответствует записи, пытаемся найти корректную существующую вариацию по содержимому.
                matched_ids = [vid for vid in existing_norm_to_ids.get(desired_key, []) if vid not in kept_ids]
                if len(matched_ids) == 1:
                    final_id = matched_ids[0]
                    logging.warning(
                        "⚠️ existing_variation_id=%s не соответствует данным строки; использован variation=%s по ключу.",
                        existing_id,
                        final_id
                    )
                else:
                    endpoint = f"products/{product_id}/variations/{existing_id}"
                    response = _wcapi_request_with_retry("PUT", endpoint, payload)
                    response.raise_for_status()
                    logging.info("♻️ Вариация обновлена: product=%s variation=%s", product_id, existing_id)
                    final_id = existing_id
        else:
            # Для пустого/битого ID из таблицы сначала пробуем найти вариацию по фактическим данным.
            matched_ids = [vid for vid in existing_norm_to_ids.get(desired_key, []) if vid not in kept_ids]
            if len(matched_ids) == 1:
                final_id = matched_ids[0]
                logging.info("🔁 Найдена существующая вариация по ключу: product=%s variation=%s", product_id, final_id)
            else:
                endpoint = f"products/{product_id}/variations"
                response = _wcapi_request_with_retry("POST", endpoint, payload)
                response.raise_for_status()
                body = response.json() or {}
                created_id = body.get("id")
                if not created_id:
                    raise RuntimeError(f"Не удалось получить ID созданной вариации (product_id={product_id})")
                final_id = int(created_id)
                logging.info("🆕 Вариация создана: product=%s variation=%s", product_id, final_id)

        if row_index is not None:
            row_to_variation_id[row_index] = final_id
        kept_ids.add(final_id)

    stale_ids = sorted(set(existing_by_id.keys()) - kept_ids)
    for variation_id in stale_ids:
        endpoint = f"products/{product_id}/variations/{variation_id}"
        response = _wcapi_request_with_retry("DELETE", endpoint, {"force": True})
        response.raise_for_status()
        logging.info("🗑️ Вариация удалена: product=%s variation=%s", product_id, variation_id)

    return row_to_variation_id

def create_variations(product_id, variation_data_list):
    """
    Создаёт вариации для variable-продукта.
    variation_data_list - список словарей с ключами:
    - regular_price (str)
    - attributes (list of dict) с ключами name и option, например:
      [{"name": "Type", "option": "Road Running"}, {"name": "Distance", "option": "10 km"}]
    """

    # Получаем список атрибутов продукта (чтобы взять их id)
    response = _wcapi_request_with_retry("GET", f"products/{product_id}")
    product = response.json()
    product_attributes = product.get("attributes", [])

    def _norm_text(value):
        if value is None:
            return ""
        return str(value).strip()

    # Создаём словарь для быстрого поиска id атрибута по имени.
    # Нормализуем ключ, чтобы "Running " и "Running" считались одним атрибутом.
    attr_name_to_id = {
        _norm_text(attr.get("name")): attr["id"]
        for attr in product_attributes
        if "id" in attr and _norm_text(attr.get("name"))
    }

    # Получаем уже существующие вариации
    existing_response = _wcapi_request_with_retry("GET", f"products/{product_id}/variations")
    existing_response.raise_for_status()
    existing_variations = existing_response.json()

    # Собираем множество уже существующих комбинаций атрибутов
    existing_combinations = set()
    for variation in existing_variations:
        combo = tuple(
            sorted(
                (_norm_text(attr.get("name")), _norm_text(attr.get("option")))
                for attr in variation.get("attributes", [])
                if _norm_text(attr.get("name")) and _norm_text(attr.get("option"))
            )
        )
        existing_combinations.add(combo)

    for var_data in variation_data_list:
        attrs_for_api = []
        # Проверка на дубликат
        combo_key = tuple(
            sorted(
                (_norm_text(attr.get("name")), _norm_text(attr.get("option")))
                for attr in var_data.get("attributes", [])
                if _norm_text(attr.get("name")) and _norm_text(attr.get("option"))
            )
        )
        if combo_key in existing_combinations:
            print(f"⚠️ Вариация уже существует, пропускаем: {combo_key}")
            continue

        for attr in var_data.get("attributes", []):
            name = _norm_text(attr.get("name"))
            option = _norm_text(attr.get("option"))

            if not name or not option:
                continue

            attr_id = attr_name_to_id.get(name)
            if not attr_id:
                print(f"⚠️ Атрибут с именем '{name}' не найден у продукта ID={product_id}, пропускаем.")
                continue

            attrs_for_api.append({
                "id": attr_id,
                "option": option
            })

        payload = {
            "regular_price": var_data.get("regular_price", "0"),
            "attributes": attrs_for_api
        }

        try:
            logging.debug(f"📤 Отправка вариации для товара {product_id}: {json.dumps(payload, ensure_ascii=False)}")
            res = _wcapi_request_with_retry("POST", f"products/{product_id}/variations", payload)
            res.raise_for_status()
            logging.debug(f"📥 Ответ WooCommerce: {res.status_code} — {res.text}")
            print("✅ Вариация создана:", payload)
        except Exception as e:
            print(f"❌ Ошибка создания вариации для продукта {product_id}:", e, res.text if 'res' in locals() else "")

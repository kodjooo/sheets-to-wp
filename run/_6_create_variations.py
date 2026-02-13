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

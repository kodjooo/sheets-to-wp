import requests
from woocommerce import API
import json
import logging

from _1_google_loader import load_config
config = load_config()

wcapi = API(
    url=config["wp_url"],
    consumer_key=config["consumer_key"],
    consumer_secret=config["consumer_secret"],
    version="wc/v3"
)

def create_variations(product_id, variation_data_list):
    """
    Создаёт вариации для variable-продукта.
    variation_data_list - список словарей с ключами:
    - regular_price (str)
    - attributes (list of dict) с ключами name и option, например:
      [{"name": "Type", "option": "Road Running"}, {"name": "Distance", "option": "10 km"}]
    """

    # Получаем список атрибутов продукта (чтобы взять их id)
    response = wcapi.get(f"products/{product_id}")
    product = response.json()
    product_attributes = product.get("attributes", [])

    # Создаём словарь для быстрого поиска id атрибута по имени
    attr_name_to_id = {attr["name"]: attr["id"] for attr in product_attributes if "id" in attr}

    # Получаем уже существующие вариации
    existing_response = wcapi.get(f"products/{product_id}/variations")
    existing_response.raise_for_status()
    existing_variations = existing_response.json()

    # Собираем множество уже существующих комбинаций атрибутов
    existing_combinations = set()
    for variation in existing_variations:
        combo = tuple(sorted((attr["name"], attr["option"]) for attr in variation.get("attributes", [])))
        existing_combinations.add(combo)

    for var_data in variation_data_list:
        attrs_for_api = []
        # Проверка на дубликат
        combo_key = tuple(sorted((attr["name"], attr["option"]) for attr in var_data.get("attributes", []) if attr.get("name") and attr.get("option")))
        if combo_key in existing_combinations:
            print(f"⚠️ Вариация уже существует, пропускаем: {combo_key}")
            continue

        for attr in var_data.get("attributes", []):
            name = attr.get("name")
            option = attr.get("option")

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
            res = wcapi.post(f"products/{product_id}/variations", payload)
            res.raise_for_status()
            logging.debug(f"📥 Ответ WooCommerce: {res.status_code} — {res.text}")
            print("✅ Вариация создана:", payload)
        except Exception as e:
            print(f"❌ Ошибка создания вариации для продукта {product_id}:", e, res.text if 'res' in locals() else "")
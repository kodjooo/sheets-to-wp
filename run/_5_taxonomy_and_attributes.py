import requests
import json
import logging
from woocommerce import API
from _1_google_loader import load_config

config = load_config()
wcapi = API(
    url=config["wp_url"],
    consumer_key=config["consumer_key"],
    consumer_secret=config["consumer_secret"],
    version="wc/v3"
)

HEADERS = {"Content-Type": "application/json"}


def get_or_create_attribute(name):
    response = wcapi.get("products/attributes")
    attributes = response.json()
    
    for attr in attributes:
        if attr['name'].lower() == name.lower():
            return attr['id']

    data = {"name": name, "type": "select"}
    new_attr = wcapi.post("products/attributes", data).json()
    return new_attr['id']


def get_or_create_attribute_term(attr_id, value):
    # Если value — это список, обрабатываем только первый элемент
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]

    if not value or value.strip() == "":
        logging.warning(f"⚠️ Пустое значение терма для атрибута ID={attr_id}, пропускаем создание терма.")
        return None

    response = wcapi.get(f"products/attributes/{attr_id}/terms")
    terms = response.json()

    for term in terms:
        if term['name'].lower() == value.lower():
            return term['id']

    data = {"name": value}
    logging.debug(f"🔧 Пытаемся создать терм '{value}' в атрибуте ID={attr_id}")
    response = wcapi.post(f"products/attributes/{attr_id}/terms", data)

    try:
        response.raise_for_status()
        term_data = response.json()
        if "id" not in term_data:
            logging.error("❌ Ответ не содержит 'id' при создании терма: %s", term_data)
            raise Exception("Нет ID в ответе от WooCommerce при создании терма")
        return term_data["id"]

    except requests.exceptions.HTTPError as e:
        if response.status_code == 400:
            try:
                error_data = response.json()
                if error_data.get("code") == "term_exists":
                    existing_id = error_data.get("data", {}).get("resource_id")
                    if existing_id:
                        logging.warning(f"⚠️ Терм '{value}' уже существует (ID={existing_id}), используем его.")
                        return existing_id
            except Exception as parse_error:
                logging.error("❌ Не удалось разобрать ошибку term_exists: %s", parse_error)

        logging.error(f"❌ Ошибка при создании терма '{value}' для атрибута {attr_id}: {response.text}")
        raise


def assign_attributes_to_product(product_id, attributes_dict):
    attr_payload = []
    variation_attrs = []

    for attr_name, value in attributes_dict.items():
        # Если value — не список, делаем списком
        values = value if isinstance(value, list) else [value]

        attr_id = get_or_create_attribute(attr_name)
        if attr_id is None:
            logging.warning(f"⚠️ Атрибут '{attr_name}' не найден и не создан — пропускаем.")
            continue

        options = []
        for val in values:
            if not isinstance(val, str) or not val.strip():
                logging.info(f"⚠️ Значение для атрибута '{attr_name}' пустое или не строка — пропускаем.")
                continue

            term_id = get_or_create_attribute_term(attr_id, val)
            if term_id is None:
                logging.warning(f"⚠️ Терм '{val}' для атрибута '{attr_name}' не создан — пропускаем.")
                continue

            options.append(val)

            variation_attrs.append({
                "id": attr_id,
                "option": val
            })

        if not options:
            logging.info(f"⚠️ Для атрибута '{attr_name}' нет валидных значений — пропускаем.")
            continue

        attr_payload.append({
            "id": attr_id,
            "variation": True,
            "visible": True,
            "options": options
        })

    if attr_payload:
        wcapi.put(f"products/{product_id}", {"attributes": attr_payload})
    else:
        logging.info(f"⚠️ Ни одного атрибута не собрано для продукта ID={product_id} — пропуск wcapi.put")

    return variation_attrs
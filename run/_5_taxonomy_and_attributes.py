import logging
import os
import time

import requests
from woocommerce import API

from _1_google_loader import load_config
from utils import select_attribute_id

config = load_config()
wcapi = API(
    url=config["wp_url"],
    consumer_key=config["consumer_key"],
    consumer_secret=config["consumer_secret"],
    version="wc/v3"
)

_WCAPI_MAX_ATTEMPTS = int(os.getenv("WCAPI_MAX_ATTEMPTS", "4"))
_WCAPI_BASE_DELAY_SEC = float(os.getenv("WCAPI_BASE_DELAY_SEC", "1.5"))


def _safe_wc_request(method: str, endpoint: str, **kwargs):
    """Execute WooCommerce API call with retry on transient connection issues."""
    last_err = None
    delay = _WCAPI_BASE_DELAY_SEC

    for attempt in range(1, _WCAPI_MAX_ATTEMPTS + 1):
        try:
            return getattr(wcapi, method)(endpoint, **kwargs)
        except requests.exceptions.RequestException as err:
            last_err = err
            if attempt == _WCAPI_MAX_ATTEMPTS:
                break

            logging.warning(
                f"⚠️ Ошибка соединения с WooCommerce {method.upper()} {endpoint} (попытка {attempt}/{_WCAPI_MAX_ATTEMPTS}): {err}"
            )
            logging.info(f"⏳ Повторная попытка обращения к WooCommerce через {delay} сек...")
            time.sleep(delay)
            delay *= 2

    raise last_err


def get_or_create_attribute(name):
    response = _safe_wc_request("get", "products/attributes")
    attributes = response.json()
    existing_id = select_attribute_id(attributes, name)
    if existing_id is not None:
        return existing_id

    data = {"name": name, "type": "select"}
    logging.debug(f"🔧 Пытаемся создать атрибут '{name}'")
    create_response = _safe_wc_request("post", "products/attributes", data=data)

    try:
        create_response.raise_for_status()
        new_attr = create_response.json()
        if "id" not in new_attr:
            raise RuntimeError(
                f"Ответ WooCommerce при создании атрибута '{name}' не содержит id: {new_attr}"
            )
        return new_attr["id"]
    except requests.exceptions.HTTPError:
        if create_response.status_code == 400:
            logging.error(
                "❌ Ошибка 400 при создании атрибута '%s': %s",
                name,
                create_response.text,
            )
            # Fallback: атрибут мог быть создан ранее/параллельно или конфликтует по slug.
            retry_attrs = _safe_wc_request("get", "products/attributes").json()
            existing_id = select_attribute_id(retry_attrs, name)
            if existing_id is not None:
                logging.warning(
                    "⚠️ Атрибут '%s' найден после 400 (ID=%s), используем его.",
                    name,
                    existing_id,
                )
                return existing_id

            raise RuntimeError(
                f"Не удалось создать атрибут '{name}': WooCommerce вернул 400, и атрибут не найден при повторном поиске. "
                f"Ответ: {create_response.text}"
            )

        raise RuntimeError(
            f"Не удалось создать атрибут '{name}': HTTP {create_response.status_code}. "
            f"Ответ: {create_response.text}"
        )


def get_or_create_attribute_term(attr_id, value):
    # Если value — это список, обрабатываем только первый элемент
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]

    if not value or value.strip() == "":
        logging.warning(f"⚠️ Пустое значение терма для атрибута ID={attr_id}, пропускаем создание терма.")
        return None

    response = _safe_wc_request("get", f"products/attributes/{attr_id}/terms")
    terms = response.json()

    for term in terms:
        if term['name'].lower() == value.lower():
            return term['id']

    data = {"name": value}
    logging.debug(f"🔧 Пытаемся создать терм '{value}' в атрибуте ID={attr_id}")
    response = _safe_wc_request("post", f"products/attributes/{attr_id}/terms", data=data)

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
        _safe_wc_request("put", f"products/{product_id}", data={"attributes": attr_payload})
    else:
        logging.info(f"⚠️ Ни одного атрибута не собрано для продукта ID={product_id} — пропуск wcapi.put")

    return variation_attrs

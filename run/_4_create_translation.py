import requests
import openai
from requests.auth import HTTPBasicAuth
from _5_taxonomy_and_attributes import assign_attributes_to_product
from _6_create_variations import create_variations
from _3_create_product import get_jwt_token
from _3_create_product import get_category_id_by_name
import logging
import json  

def create_product_pt(row, en_product_id, attributes=None, last_variations=None, config=None):
    auth = HTTPBasicAuth(config["consumer_key"], config["consumer_secret"])
    base_url = config["wp_url"]

    logging.info("🌍 Создаём перевод продукта на португальский")
    logging.debug("📦 Получены last_variations в create_product_pt: %s", json.dumps(last_variations or [], ensure_ascii=False))

    # Получаем slug оригинала
    response_en = requests.get(
        f"{base_url}/wp-json/wc/v3/products/{en_product_id}",
        auth=auth
    )
    response_en.raise_for_status()
    en_product_data = response_en.json()
    original_slug = en_product_data.get("slug", "")

    # Формируем данные для перевода с правильным slug
    data = {
        "title": row.get("RACE NAME (PT)", "") or row.get("RACE NAME", ""),
        "status": "draft",
        "lang": "pt",
        "slug": original_slug if original_slug else "",
        "translations": {
            "en": en_product_id
        }
    }

    # # Вместо загрузки новой картинки используем уже существующий ID от оригинала
    # image_id = row.get("IMAGE ID") or row.get("image_id")
    # if image_id:
    #     data["featured_media"] = int(image_id)

    logging.debug("📦 Данные для перевода: %s", json.dumps(data, ensure_ascii=False))

    try:
        categories_raw = set()
        main_category = row.get("CATEGORY")
        main_subcategory = row.get("SUBCATEGORY")
        if main_category:
            categories_raw.add((main_category, main_subcategory))
            logging.debug(f"📂 Основная категория PT: ({main_category} → {main_subcategory})")

        extra_cats = row.get("extra_categories")
        if isinstance(extra_cats, (set, list)):
            valid = []
            for item in extra_cats:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    category_name, subcategory_name = item
                    if category_name:
                        valid.append((category_name, subcategory_name))
            if valid:
                logging.debug(f"📚 Доп. категории PT получены: {valid}")
                categories_raw.update(valid)
            else:
                logging.debug(f"⚠️ Доп. категории PT найдены, но не в формате пар (name, value): {extra_cats}")
        else:
            logging.debug("📚 Доп. категории PT отсутствуют или в неправильном формате")

        category_ids = []
        for parent_name, child_name in categories_raw:
            try:
                parent_id = get_category_id_by_name(parent_name)
                if parent_id:
                    category_ids.append({"id": parent_id})
                    if child_name:
                        child_id = get_category_id_by_name(child_name, parent_id=parent_id)
                        if child_id:
                            category_ids.append({"id": child_id})
            except Exception as e:
                logging.warning(f"⚠️ Ошибка при добавлении категории ({parent_name} → {child_name}): {e}")

        if category_ids:
            data["categories"] = category_ids
        response = requests.post(
            f"{base_url}/wp-json/wc/v3/products",
            auth=auth,
            json=data
        )
        response.raise_for_status()
        json_data = response.json()

        pt_id = json_data.get("id")
        logging.info(f"✅ Перевод создан: ID={pt_id}")
        if not pt_id:
            raise Exception("Перевод не был создан")

        # # 🖼️ Присваиваем изображение через wp/v2
        # if image_id:
        #     token = get_jwt_token()  # Функция должна быть определена, ты её уже используешь
        #     wp_response = requests.post(
        #         f"{base_url}/wp-json/wp/v2/product/{pt_id}",
        #         headers={
        #             "Authorization": f"Bearer {token}",
        #             "Content-Type": "application/json"
        #         },
        #         json={"featured_media": int(image_id)}
        #     )
        #     if wp_response.ok:
        #         logging.info(f"🖼️ Картинка успешно обновлена через wp/v2 для PT-продукта ID={pt_id}")
        #     else:
        #         logging.warning(f"❌ Ошибка при обновлении картинки через wp/v2: {wp_response.status_code} — {wp_response.text}")


        # 💾 Обновляем повторно title (его WPML может сбросить)
        update_payload = {
            "name": row.get("RACE NAME (PT)", "") or row.get("RACE NAME", ""),
            "lang": "pt"
        }
        update_response = requests.put(
            f"{base_url}/wp-json/wc/v3/products/{pt_id}",
            auth=auth,
            json=update_payload
        )
        if update_response.status_code == 200:
            logging.info(f"✅ Название обновлено у перевода PT-продукта ID={pt_id}")
        else:
            logging.warning(f"⚠️ Название не обновлено! Код={update_response.status_code}, ответ={update_response.text}")

        # 🔄 Обновляем ACF-поля через ACF REST API
        benefits_pt = row.get("BENEFITS (PT)", "")
        if isinstance(benefits_pt, list):
            benefits_pt = "\n".join(benefits_pt)

        meta_update_payload = {
            "meta_data": [
                {"key": "event_short_description", "value": row.get("SUMMARY (PT)", "")},
                {"key": "organizer_description", "value": row.get("ORG INFO (PT)", "")},
                {"key": "race_benefits", "value": benefits_pt}
            ]
        }
        meta_update_response = requests.put(
            f"{base_url}/wp-json/wc/v3/products/{pt_id}",
            auth=auth,
            json=meta_update_payload
        )
        if meta_update_response.status_code == 200:
            logging.info(f"✅ ACF-поля (meta_data) обновлены у PT-продукта ID={pt_id}")
        else:
            logging.warning(f"⚠️ meta_data не обновлены! Код={meta_update_response.status_code}, ответ={meta_update_response.text}")

        # 📡 Отправляем связку перевода на WPML
        hook_payload = {
            "original_id": en_product_id,
            "translated_id": pt_id,
            "lang_code": "pt"
        }

        logging.info("🔗 Пытаемся связать перевод с оригиналом через WPML API")
        logging.debug("📨 Данные для связывания: %s", json.dumps(hook_payload))

        try:
            hook_response = requests.post(
                f"{base_url}/wp-json/custom-api/v1/set-translation/",
                json=hook_payload,
                auth=auth
            )

            logging.debug("📡 Ответ WPML API: %s", hook_response.text)

            if not hook_response.ok:
                logging.error(f"❌ Связь через WPML API не удалась: {hook_response.status_code} — {hook_response.text}")
            else:
                logging.info(f"✅ Перевод успешно связан: EN={en_product_id} ⇄ PT={pt_id}")

        except Exception as hook_error:
            logging.exception(f"❌ Ошибка при связывании перевода через WPML API: {hook_error}")

        # Присваиваем атрибуты и создаём вариации
        if attributes:
            logging.debug("🧩 Присваиваемые атрибуты: %s", json.dumps(attributes, ensure_ascii=False))
            assign_attributes_to_product(pt_id, attributes)
        if last_variations:
            logging.info(f"🔁 Создаём вариации для PT-продукта ID={pt_id}")
            logging.debug("🧬 last_variations для create_variations: %s", json.dumps(last_variations, ensure_ascii=False))
            create_variations(pt_id, last_variations)
        else:
            logging.warning("⚠️ last_variations пуст или не передан — вариации не будут созданы")

        return pt_id

    except Exception as e:
        raise Exception(f"Ошибка при создании перевода: {e}")

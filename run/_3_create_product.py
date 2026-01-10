import json
import requests
import base64
import os
import datetime
import openai
from io import BytesIO
from PIL import Image
from wordpress_xmlrpc import Client, WordPressPost
from wordpress_xmlrpc.methods import media, posts
from wordpress_xmlrpc.compat import xmlrpc_client

from _1_google_loader import load_config
from utils import normalize_category_pairs

config = load_config()

WC_API_URL = config["wp_url"]
WC_CONSUMER_KEY = config["consumer_key"]
WC_CONSUMER_SECRET = config["consumer_secret"]

headers = {
    "Content-Type": "application/json"
}

def download_image_from_url(image_url):
    """
    Загружает изображение по URL и сохраняет его локально во временный файл.
    Возвращает путь к локальному файлу.
    """
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        filename = "generated_image.jpg"
        path = f"/tmp/{filename}"
        img.convert("RGB").save(path, format="JPEG", quality=90)
        return path
    except Exception as e:
        print(f"⚠️ Ошибка при загрузке изображения по URL: {e}")
        return None

def upload_image_from_path(image_path, token):
    try:
        with open(image_path, "rb") as img:
            image_data = img.read()
        filename = os.path.basename(image_path)

        response = requests.post(
            WC_API_URL + "/wp-json/wp/v2/media",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "image/jpeg"
            },
            data=image_data
        )
        response.raise_for_status()
        return response.json()["id"]

    except requests.exceptions.HTTPError as e:
        print(f"🔥 HTTP ошибка при загрузке изображения в WP: {e}")
        if e.response is not None:
            print(f"📦 Код ответа: {e.response.status_code}")
            try:
                print("📄 Ответ сервера:", e.response.json())
            except ValueError:
                print("📄 Ответ сервера (не JSON):", e.response.text)
        return None

    except Exception as e:
        print(f"⚠️ Другая ошибка загрузки изображения в WP: {e}")
        return None

def get_category_id_by_name(name, parent_id=None):
    """
    Возвращает ID категории WooCommerce по названию.
    Если такой нет — создаёт.
    Если parent_id указан, ищет категорию с этим родителем.
    Если parent_id не указан — ищет категорию с parent == 0 (верхний уровень).
    """
    # Ищем категорию по имени
    response = requests.get(
        WC_API_URL + "/wp-json/wc/v3/products/categories",
        auth=(WC_CONSUMER_KEY, WC_CONSUMER_SECRET),
        params={"search": name}
    )
    response.raise_for_status()
    print("🔍 Ответ от WooCommerce (категории):", response.text)
    categories = response.json()

    print(f"🔍 Поиск категории '{name}': {len(categories)} найдено")
    # Фильтруем категории по точному совпадению имени
    matched = [cat for cat in categories if cat["name"].lower() == name.lower()]

    # Если есть parent_id — фильтруем по нему
    if parent_id is not None:
        matched = [cat for cat in matched if cat.get("parent") == parent_id]
    else:
        # Если parent_id не указан — ищем категории с parent == 0 (верхний уровень)
        matched = [cat for cat in matched if cat.get("parent") == 0]

    if matched:
        cat = matched[0]
        print(f"✅ Найдена точная категория '{name}' с ID {cat['id']} (parent: {cat.get('parent')})")
        return cat["id"]

    print(f"❌ Точная категория '{name}' не найдена с parent_id={parent_id}")

    # Если не найдено — создаём категорию
    payload = {
        "name": name,
        "slug": name.lower().replace(" ", "-")
    }
    if parent_id:
        payload["parent"] = parent_id
    create_response = requests.post(
        WC_API_URL + "/wp-json/wc/v3/products/categories",
        auth=(WC_CONSUMER_KEY, WC_CONSUMER_SECRET),
        headers=headers,
        data=json.dumps(payload)
    )
    create_response.raise_for_status()
    print("🔍 Ответ от WooCommerce (категория создана):", create_response.text)
    created_cat = create_response.json()
    print(f"🆕 Создана категория '{name}' с ID {created_cat.get('id')}")
    return created_cat.get("id")

def get_jwt_token():
    admin_username = config["wp_admin_user"]
    admin_password = config["wp_admin_pass"]

    response = requests.post(
        f"{WC_API_URL}/wp-json/jwt-auth/v1/token",
        headers={"Content-Type": "application/json"},
        data=json.dumps({
            "username": admin_username,
            "password": admin_password
        })
    )
    response.raise_for_status()
    token = response.json().get("token")
    print("🔑 Получен новый JWT токен")
    return token

def format_date_ymd(date_str):
    if not date_str:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            dt = datetime.datetime.strptime(date_str, fmt)
            return dt.strftime("%Y%m%d")
        except ValueError:
            continue
    return ""


def send_acf_data(product_id, acf_data, token):
    acf_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    acf_response = requests.post(
        f"{WC_API_URL}/wp-json/acf/v3/product/{product_id}",
        headers=acf_headers,
        data=json.dumps(acf_data)
    )

    # Если токен истёк или неверен — получим новый и попробуем снова
    if acf_response.status_code == 401:
        print("🔁 Токен истёк, получаем новый и повторяем запрос...")
        token = get_jwt_token()
        acf_headers["Authorization"] = f"Bearer {token}"
        acf_response = requests.post(
            f"{WC_API_URL}/wp-json/acf/v3/product/{product_id}",
            headers=acf_headers,
            data=json.dumps(acf_data)
        )

    return acf_response

def create_product(data):
    print("👉 Данные перед созданием товара:")
    print(json.dumps(data, indent=2, ensure_ascii=False))

    data["EVENT START DATE"] = format_date_ymd(data.get("EVENT START DATE", ""))
    data["EVENT END DATE"] = format_date_ymd(data.get("EVENT END DATE", ""))

    # Формируем данные для основного товара
    product_data = {
        "name": data["RACE NAME"],
        "type": "variable",
        "status": "draft"
    }

    # Получаем категории из таблицы
    categories_raw = []

    main_category = data.get("CATEGORY")
    main_subcategory = data.get("SUBCATEGORY")
    if main_category:
        categories_raw.append((main_category, main_subcategory))
        print(f"📂 Основная категория: ({main_category} → {main_subcategory})")
    else:
        print("📂 Основная категория не указана в строке")

    extra_cats = data.get("extra_categories")
    if isinstance(extra_cats, (list, set)):
        valid = []
        for item in extra_cats:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                category_name, subcategory_name = item
                if category_name:
                    valid.append((category_name, subcategory_name))
        if valid:
            print(f"📚 Доп. категории получены: {valid}")
            categories_raw.extend(valid)
        else:
            print(f"⚠️ Доп. категории найдены, но не в формате пар (name, value): {extra_cats}")
    else:
        print("📚 Доп. категории отсутствуют или в неправильном формате")

    categories_normalized = normalize_category_pairs(categories_raw)
    if categories_normalized:
        print(f"📦 Нормализованные категории: {categories_normalized}")

    category_ids = []
    category_ids_seen = set()
    for parent_name, child_name in categories_normalized:
        try:
            parent_id = get_category_id_by_name(parent_name)
            if parent_id:
                if parent_id not in category_ids_seen:
                    category_ids.append({"id": parent_id})
                    category_ids_seen.add(parent_id)
                if child_name:
                    child_id = get_category_id_by_name(child_name, parent_id=parent_id)
                    if child_id:
                        if child_id not in category_ids_seen:
                            category_ids.append({"id": child_id})
                            category_ids_seen.add(child_id)
        except Exception as e:
            print(f"⚠️ Ошибка при добавлении категории ({parent_name} → {child_name}): {e}")

    product_data["categories"] = category_ids

    print("👉 Категории перед отправкой:", product_data.get("categories"))

    # # Загрузка изображения, если указан image_url
    # image_id = data.get("IMAGE ID")

    # if image_id:
    #     print(f"🖼 Используем уже загруженное изображение с ID: {image_id}")
    #     product_data["images"] = [{"id": int(image_id)}]
    # elif "IMAGE URL" in data and data["IMAGE URL"]:
    #     # Только если image_id отсутствует, пробуем загрузить
    #     try:
    #         token = get_jwt_token()
    #         local_path = download_image_from_url(data["IMAGE URL"])
    #         if local_path:
    #             uploaded_id = upload_image_from_path(local_path, token)
    #             if uploaded_id:
    #                 print(f"🖼 Изображение загружено, ID: {uploaded_id}")
    #                 product_data["images"] = [{"id": uploaded_id}]
    #                 data["IMAGE ID"] = uploaded_id  # можно обновить в таблице, если хочешь
    #             else:
    #                 print("❌ Не удалось загрузить изображение: image_id = None")
    #             os.remove(local_path)
    #     except Exception as e:
    #         print(f"⚠️ Ошибка загрузки изображения: {e}")

    # Основной POST-запрос для создания товара
    try:
        response = requests.post(
            WC_API_URL + "/wp-json/wc/v3/products",
            auth=(WC_CONSUMER_KEY, WC_CONSUMER_SECRET),
            headers=headers,
            data=json.dumps(product_data)
        )
        print("🧾 Ответ от WP при создании товара:", response.status_code, response.text)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"🔥 HTTP ошибка при создании товара: {e}")
        if e.response is not None:
            try:
                print("📄 Ответ сервера (JSON):", e.response.json())
            except Exception:
                print("📄 Ответ сервера (текст):", e.response.text)
        return None  # или обработать ошибку иначе, например, пробросить
    else:
        product_id = response.json()["id"]
        print("📦 Продукт создан:", product_id)

    from decimal import Decimal, ROUND_DOWN

    def format_coord(value):
        return float(Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_DOWN))

    # ACF данные
    benefits = data.get("BENEFITS", "")
    if isinstance(benefits, list):
        benefits = "\n".join(benefits)

    acf_data = {
        "fields": {
            "event_date_start": data["EVENT START DATE"],
            "event_location_text": data["LOCATION"].split(",")[0] if data.get("LOCATION") else "",
            "event_ticket_url": data["WEBSITE"],
            "event_latitude": format_coord(data["LAT"]) if data.get("LAT") else "",
            "event_longitude": format_coord(data["LON"]) if data.get("LON") else "",
            "event_short_description": data["SUMMARY"],
            "organizer_description": data["ORG INFO"],
            "race_benefits": benefits,
            "event_country": "portugal",
            "event_start_time": data.get("EVENT START TIME", ""),
            "event_date_end": data["EVENT END DATE"]
        }
    }

    print("📤 Отправляем ACF-поля через отдельный запрос:")
    print(json.dumps(acf_data, indent=2, ensure_ascii=False))

    token = get_jwt_token()
    acf_response = send_acf_data(product_id, acf_data, token)

    if acf_response.status_code not in [200, 201]:
        print("⚠️ Ошибка при обновлении ACF:", acf_response.status_code, acf_response.text)
    else:
        print("✅ ACF поля успешно обновлены")

    return product_id

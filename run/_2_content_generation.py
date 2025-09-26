import requests
import time
import json
import openai
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from PIL import Image
from io import BytesIO
import base64
import logging
import re
from _1_google_loader import load_config, get_logger
from _3_create_product import get_jwt_token

logger = get_logger()
logger.setLevel(logging.DEBUG)
config = load_config()
openai.api_key = config['openai_api_key']
OPENCAGE_API_KEY = config.get("opencage_api_key")

def convert_google_drive_url(url):
    """
    Преобразует Google Drive ссылку в прямую ссылку для скачивания.
    Поддерживает формат: https://drive.google.com/file/d/FILE_ID/view
    Возвращает: https://drive.google.com/uc?export=download&id=FILE_ID
    """
    # Проверяем, является ли это ссылкой на Google Drive
    google_drive_pattern = r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)/'
    match = re.search(google_drive_pattern, url)
    
    if match:
        file_id = match.group(1)
        direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        logger.info(f"🔗 Преобразована Google Drive ссылка: {url} → {direct_url}")
        return direct_url
    
    # Если это не Google Drive ссылка, возвращаем исходную
    return url

def extract_text_from_url(url):
    try:
        # Преобразуем Google Drive ссылку в прямую ссылку, если необходимо
        direct_url = convert_google_drive_url(url)
        
        if direct_url.lower().endswith(".pdf") or "drive.google.com/uc?export=download" in direct_url:
            # Для PDF файлов (включая Google Drive)
            response = requests.get(direct_url)
            response.raise_for_status()
            
            # Проверяем, что получили именно PDF, а не HTML страницу с ошибкой
            content_type = response.headers.get('content-type', '').lower()
            if 'text/html' in content_type and 'drive.google.com' in direct_url:
                logger.warning(f"⚠️ Google Drive файл может быть недоступен для публичного скачивания: {url}")
                logger.warning("⚠️ Убедитесь, что файл имеет публичный доступ")
                return "", None
            
            pdf_path = "/tmp/temp.pdf"
            with open(pdf_path, "wb") as f:
                f.write(response.content)
            logger.info(f"📄 Обнаружен PDF: {url}")
            return "", pdf_path
        else:
            # Для обычных веб-страниц
            response = requests.get(direct_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
            logger.info(f"🌐 Обработан сайт: {url}")
            return text.strip(), None
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки из {url}: {e}")
        return "", None

def translate_title_to_pt(title: str) -> str:
    """
    Переводит заголовок с английского на португальский через GPT.
    """
    if not title:
        return ""
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional translator."},
                {"role": "user", "content": f"Translate this race name from English to Portuguese without changing the meaning or inventing anything:\n\n{title}"}
            ],
            temperature=0.3
        )
        pt_title = response.choices[0].message.content.strip()
        logger.info(f"🌍 Переведён заголовок: '{title}' → '{pt_title}'")
        return pt_title
    except Exception as e:
        logger.error(f"❌ Ошибка при переводе заголовка: {e}")
        return ""

def call_openai_assistant(text, file_ids=None, has_pdf=False):
    try:
        thread = openai.beta.threads.create()
        logger.info("💬 Создан новый тред")

        assistant_id = config["assistant_id_pdf"] if has_pdf else config["assistant_id_text"]

        logger.debug("📤 Отправляем в GPT (assistant_id=%s):\n%s", assistant_id, text[:40000])

        # Создаём сообщение — прикрепляем файлы, если есть
        if file_ids:
            openai.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=text[:40000],
                attachments=[{"file_id": file_id, "tools": [{"type": "file_search"}]} for file_id in file_ids]
            )
        else:
            openai.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=text[:40000]
            )

        # Запускаем ассистента
        run = openai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant_id
            # ⬅️ Больше ничего сюда не передаём!
        )

        # Ждём завершения с таймаутом
        max_attempts = 60  # 2 минуты максимум (60 * 2 секунды)
        attempt = 0
        
        while attempt < max_attempts:
            status = openai.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            if status.status == "completed":
                break
            elif status.status in ["failed", "cancelled"]:
                logger.error("❌ Ошибка выполнения ассистента")
                return None
            elif status.status == "expired":
                logger.error("❌ Время выполнения ассистента истекло")
                return None
            
            attempt += 1
            logger.debug(f"⏳ Попытка {attempt}/{max_attempts}, статус: {status.status}")
            time.sleep(2)
        
        if attempt >= max_attempts:
            logger.error("❌ Превышено время ожидания OpenAI ассистента")
            return None

        messages = openai.beta.threads.messages.list(thread_id=thread.id)
        reply = messages.data[0].content[0].text.value
        return json.loads(reply)

    except Exception as e:
        logger.error(f"❌ Ошибка OpenAI: {e}")
        return None

def call_second_openai_assistant(first_result):
    """
    Вызывает второй ассистент GPT с результатом первого ассистента.
    """
    try:
        thread = openai.beta.threads.create()
        logger.info("💬 Создан новый тред для второго ассистента")

        assistant_id = config["assistant_id_second"]
        
        # Конвертируем результат первого ассистента в текст для отправки
        if isinstance(first_result, dict):
            text_content = json.dumps(first_result, ensure_ascii=False, indent=2)
        else:
            text_content = str(first_result)

        logger.debug("📤 Отправляем во второй ассистент (assistant_id=%s):\n%s", assistant_id, text_content[:40000])

        # Создаём сообщение
        openai.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=text_content[:40000]
        )

        # Запускаем второй ассистент
        run = openai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant_id
        )

        # Ждём завершения с таймаутом
        max_attempts = 60  # 2 минуты максимум
        attempt = 0
        
        while attempt < max_attempts:
            status = openai.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            if status.status == "completed":
                break
            elif status.status in ["failed", "cancelled"]:
                logger.error("❌ Ошибка выполнения второго ассистента")
                return None
            elif status.status == "expired":
                logger.error("❌ Время выполнения второго ассистента истекло")
                return None
            
            attempt += 1
            logger.debug(f"⏳ Попытка {attempt}/{max_attempts}, статус: {status.status}")
            time.sleep(2)
        
        if attempt >= max_attempts:
            logger.error("❌ Превышено время ожидания второго OpenAI ассистента")
            return None

        messages = openai.beta.threads.messages.list(thread_id=thread.id)
        reply = messages.data[0].content[0].text.value
        return json.loads(reply)

    except Exception as e:
        logger.error(f"❌ Ошибка второго ассистента OpenAI: {e}")
        return None

def get_coordinates_from_location(location: str):
    if not location:
        return None, None
    url = f"https://api.opencagedata.com/geocode/v1/json?q={location}&key={OPENCAGE_API_KEY}&language=en&limit=1"
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    if data["results"]:
        lat = data["results"][0]["geometry"]["lat"]
        lon = data["results"][0]["geometry"]["lng"]
        return lat, lon
    return None, None

def check_wp_upload(jwt_token):
    wp_url = config["wp_url"].rstrip("/") + "/wp-json/wp/v2/media"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Disposition": "attachment; filename=test.png"
    }
    minimal_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgHKqLzMAAAAASUVORK5CYII="
    )

    try:
        response = requests.post(wp_url, headers=headers, files={"file": ("test.png", minimal_png)})
        if response.status_code == 201:
            media_id = response.json().get("id")
            logger.info(f"✅ Проверка загрузки в WP успешна, media ID: {media_id}")

            # Удаляем тестовый файл сразу
            delete_url = f"{wp_url}/{media_id}?force=true"
            del_resp = requests.delete(delete_url, headers={"Authorization": f"Bearer {jwt_token}"})
            if del_resp.status_code == 200:
                logger.info("🗑️ Тестовый файл удалён из WP")
            else:
                logger.warning(f"⚠️ Не удалось удалить тестовый файл: статус {del_resp.status_code}")

            return True
        else:
            logger.error(f"❌ Проверка загрузки в WP неудачна: статус {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка проверки загрузки в WP: {e}")
        return False

def generate_image(prompt):
    jwt_token = get_jwt_token()
    if not check_wp_upload(jwt_token):
        logger.error("❌ Не удалось загрузить изображение в WP (проверка перед генерацией). Прекращаем генерацию.")
        return None

    def upload_to_wp(image_bytes, filename, jwt_token):
        try:
            wp_url = config["wp_url"].rstrip("/") + "/wp-json/wp/v2/media"
            headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Content-Disposition": f"attachment; filename={filename}"
            }

            response = requests.post(wp_url, headers=headers, files={"file": (filename, image_bytes)})
            response.raise_for_status()
            wp_response = response.json()
            logger.info(f"🖼️ Загружено в WP: {wp_response.get('source_url')}")
            return {
                "id": wp_response.get("id"),
                "url": wp_response.get("source_url")
            }
        except Exception as e:
            logger.error(f"❌ Не удалось загрузить изображение в WordPress: {e}")
            return None

    try:
        model_name = "gpt-image-1"
        logger.info(f"🎨 Генерируем через {model_name}...")
        kwargs = {
            "model": model_name,
            "prompt": prompt,
            "n": 1,
            "quality": "high",
            "size": "1024x1024"
        }

        response = openai.images.generate(**kwargs)
        data = response.data[0]

        if hasattr(data, "url") and data.url:
            image_response = requests.get(data.url)
            image_response.raise_for_status()
            image_bytes = image_response.content
        elif hasattr(data, "b64_json") and data.b64_json:
            image_bytes = base64.b64decode(data.b64_json)
        else:
            logger.warning(f"⚠️ Нет изображения в ответе от {model_name}")
            return None

        filename = f"{int(time.time())}.png"
        image_info = upload_to_wp(image_bytes, filename, jwt_token)
        if image_info and "id" in image_info and "url" in image_info:
            return image_info  # Возвращаем dict: {'url': ..., 'id': ...}

    except Exception as e:
        logger.warning(f"⚠️ Ошибка генерации через {model_name}: {e}")

    return None
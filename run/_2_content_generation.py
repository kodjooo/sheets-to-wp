import json
import logging
import os
import re
import time
import base64
from io import BytesIO
import requests
import openai
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from PIL import Image
from openai import OpenAI
from _1_google_loader import load_config, get_logger
from _3_create_product import get_jwt_token
from translation_prompt import build_translation_messages
from url_utils import normalize_http_url

logger = get_logger()
config = load_config()
openai.api_key = config['openai_api_key']
OPENCAGE_API_KEY = config.get("opencage_api_key")
_OPENAI_CLIENT = OpenAI()

def _parse_retry_delays(value: str | None) -> list[float]:
    if not value:
        return []
    delays = []
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            delays.append(float(item))
        except ValueError:
            logger.warning("⚠️ Некорректное значение задержки ретрая: %s", item)
    return delays

def _build_request_headers() -> dict:
    user_agent = config.get("fetch_user_agent") or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,pt-PT;q=0.8,pt;q=0.7"
    }

def _fetch_with_retries(url: str):
    delays = _parse_retry_delays(config.get("fetch_retry_delays_sec"))
    attempts = [0.0] + delays
    last_err = None
    for attempt_index, delay in enumerate(attempts, start=1):
        if delay:
            logger.info("⏳ Повторная попытка загрузки через %s сек...", delay)
            time.sleep(delay)
        try:
            response = requests.get(url, headers=_build_request_headers(), timeout=20)
            response.raise_for_status()
            return response
        except Exception as exc:
            last_err = exc
            logger.warning(
                "⚠️ Ошибка загрузки из %s (попытка %s/%s): %s",
                url,
                attempt_index,
                len(attempts),
                exc
            )
    raise last_err


def _load_prompt_file(path: str) -> str:
    if not path:
        return ""

    full_path = path
    if not os.path.isabs(path):
        full_path = os.path.join(os.path.dirname(__file__), path)

    try:
        with open(full_path, "r", encoding="utf-8") as prompt_file:
            return prompt_file.read().strip()
    except FileNotFoundError:
        logger.error("❌ Не найден файл промпта: %s", full_path)
    except Exception as exc:
        logger.error("❌ Ошибка чтения промпта %s: %s", full_path, exc)
    return ""


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
        normalized_url = normalize_http_url(url)
        if not normalized_url:
            logger.warning("⚠️ Пустой URL, пропускаем загрузку")
            return "", None
        direct_url = convert_google_drive_url(normalized_url)
        
        if direct_url.lower().endswith(".pdf") or "drive.google.com/uc?export=download" in direct_url:
            # Для PDF файлов (включая Google Drive)
            response = _fetch_with_retries(direct_url)
            
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
            response = _fetch_with_retries(direct_url)
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
            logger.info("🌐 Обработан сайт: %s", url)
            logger.debug(
                "🌐 Метаданные сайта: status=%s, content-type=%s, text_len=%s",
                response.status_code,
                response.headers.get("content-type", ""),
                len(text.strip())
            )
            return text.strip(), None
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки из {url}: {e}")
        return "", None

def build_first_assistant_prompt(regulations_url: str, regulations_text: str, website_text: str) -> str:
    parts = []
    if regulations_url:
        parts.append(f"REGULATIONS LINK:\n{regulations_url}")
    if regulations_text:
        parts.append(f"REGULATIONS INFO:\n{regulations_text}")
    if website_text:
        parts.append(f"WEBSITE INFO:\n{website_text}")
    return "\n\n".join(parts).strip()

def validate_source_texts(
    website_url: str,
    website_text: str,
    regulations_url: str,
    regulations_text: str,
    regulations_pdf_path: str | None
) -> list[str]:
    errors = []
    if website_url and not (website_text or "").strip():
        errors.append("WEBSITE parse failed")
    if regulations_url and not (regulations_text or "").strip() and not regulations_pdf_path:
        errors.append("REGULATIONS parse failed")
    return errors

def normalize_regulations_link_block(payload: dict, regulations_url: str) -> dict:
    if not isinstance(payload, dict) or not regulations_url:
        return payload
    link_html = (
        f'<strong><a class="" href="{regulations_url}" target="_new" rel="noopener">'
        "Regulation link ↗</a></strong>"
    )
    link_html_pt = (
        f'<strong><a class="" href="{regulations_url}" target="_new" rel="noopener">'
        "Regulamento ↗</a></strong>"
    )
    org_info = payload.get("org_info", "")
    if isinstance(org_info, str) and "Regulation link ↗" in org_info:
        lines = org_info.splitlines()
        for i, line in enumerate(lines):
            if "Regulation link ↗" in line:
                lines[i] = link_html
                break
        payload["org_info"] = "\n".join(lines)
    org_info_pt = payload.get("org_info_pt", "")
    if isinstance(org_info_pt, str) and "Regulamento ↗" in org_info_pt:
        lines = org_info_pt.splitlines()
        for i, line in enumerate(lines):
            if "Regulamento ↗" in line:
                lines[i] = link_html_pt
                break
        payload["org_info_pt"] = "\n".join(lines)
    return payload

def translate_title_to_en(title: str) -> str:
    """
    Переводит заголовок с португальского на английский через GPT.
    """
    if not title:
        return ""
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=build_translation_messages(title),
            temperature=0.3
        )
        en_title = response.choices[0].message.content.strip()
        logger.info(f"🌍 Переведён заголовок (PT→EN): '{title}' → '{en_title}'")
        return en_title
    except Exception as e:
        logger.error(f"❌ Ошибка при переводе заголовка: {e}")
        return ""

def call_openai_assistant(text, file_ids=None):
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            model = config["openai_text_model"]
            system_prompt = _load_prompt_file(config["openai_system_prompt_file"])
            user_prompt = text

            logger.info("🤖 Отправка в OpenAI Responses API, модель: %s", model)
            if system_prompt:
                logger.debug("🧾 System промпт (до 10000 символов):\n%s", system_prompt[:10000])
            logger.debug("🧾 User промпт (до 40000 символов):\n%s", user_prompt[:40000])
            if file_ids:
                logger.info("📎 Файлы для OpenAI: %s", ", ".join(file_ids))

            user_content = [{"type": "input_text", "text": user_prompt[:40000]}]
            for file_id in file_ids or []:
                user_content.append({"type": "input_file", "file_id": file_id})

            input_payload = []
            if system_prompt:
                strict_note = ""
                if attempt > 1:
                    strict_note = "\n\nСТРОГО: Верни только валидный завершённый JSON без обрезанных строк, без текста вне JSON."
                input_payload.append(
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt + strict_note}]}
                )
            input_payload.append({"role": "user", "content": user_content})

            request_kwargs = {
                "model": model,
                "input": input_payload,
            }
            reasoning_effort = config.get("openai_text_reasoning_effort")
            if reasoning_effort:
                logger.info("🧠 Уровень размышления для текста: %s", reasoning_effort)
                request_kwargs["reasoning"] = {"effort": reasoning_effort}
            temperature = config.get("openai_text_temperature")
            if temperature:
                lowered_model = (model or "").lower()
                if lowered_model.startswith(("gpt-5", "o1")):
                    logger.info("🌡️ Температура для текста пропущена для модели: %s", model)
                else:
                    request_kwargs["temperature"] = float(temperature)
                    logger.info("🌡️ Температура для текста: %s", temperature)

            try:
                response = _OPENAI_CLIENT.responses.create(**request_kwargs)
            except Exception as e:
                message = str(e)
                if "Unsupported parameter: 'temperature'" in message and "temperature" in request_kwargs:
                    logger.warning("⚠️ Модель не поддерживает temperature, повторяем без неё.")
                    request_kwargs.pop("temperature", None)
                    response = _OPENAI_CLIENT.responses.create(**request_kwargs)
                else:
                    raise

            reply = response.output_text or ""
            try:
                return json.loads(reply)
            except json.JSONDecodeError:
                logger.error("❌ Ответ OpenAI не является JSON: %s", reply[:2000])
                if attempt == max_attempts:
                    raise ValueError("Ответ OpenAI не является JSON")
                continue

        except Exception as e:
            logger.error("❌ Ошибка OpenAI Responses API (попытка %s/%s): %s", attempt, max_attempts, e)
            if attempt == max_attempts:
                return None

def call_second_openai_assistant(first_result, regulations_hint: str | None = None):
    """
    Вызывает второй запрос OpenAI Responses API с результатом первого ассистента.
    """
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            model = config["openai_second_model"]
            system_prompt = _load_prompt_file(config["openai_second_system_prompt_file"])
            if isinstance(first_result, dict):
                text_content = json.dumps(first_result, ensure_ascii=False, indent=2)
            else:
                text_content = str(first_result)
            if regulations_hint:
                user_prompt = f"{regulations_hint}\n{text_content}"
            else:
                user_prompt = text_content

            logger.info("🤖 Отправка во второй Responses API, модель: %s", model)
            logger.debug("📤 Второй промпт (до 40000 символов):\n%s", user_prompt[:40000])

            input_payload = []
            if system_prompt:
                input_payload.append(
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]}
                )
            input_payload.append(
                {"role": "user", "content": [{"type": "input_text", "text": user_prompt[:40000]}]}
            )

            request_kwargs = {
                "model": model,
                "input": input_payload,
            }
            reasoning_effort = config.get("openai_second_reasoning_effort")
            if reasoning_effort:
                logger.info("🧠 Уровень размышления для второго шага: %s", reasoning_effort)
                request_kwargs["reasoning"] = {"effort": reasoning_effort}
            temperature = config.get("openai_second_temperature")
            if temperature:
                lowered_model = (model or "").lower()
                if lowered_model.startswith(("gpt-5", "o1")):
                    logger.info("🌡️ Температура для второго шага пропущена для модели: %s", model)
                else:
                    request_kwargs["temperature"] = float(temperature)
                    logger.info("🌡️ Температура для второго шага: %s", temperature)

            try:
                response = _OPENAI_CLIENT.responses.create(**request_kwargs)
            except Exception as e:
                message = str(e)
                if "Unsupported parameter: 'temperature'" in message and "temperature" in request_kwargs:
                    logger.warning("⚠️ Модель не поддерживает temperature, повторяем без неё.")
                    request_kwargs.pop("temperature", None)
                    response = _OPENAI_CLIENT.responses.create(**request_kwargs)
                else:
                    raise

            reply = response.output_text or ""
            try:
                return json.loads(reply)
            except json.JSONDecodeError:
                logger.error("❌ Ответ второго OpenAI не является JSON: %s", reply[:2000])
                raise ValueError("Ответ второго OpenAI не является JSON")

        except Exception as e:
            logger.error("❌ Ошибка второго OpenAI Responses API (попытка %s/%s): %s", attempt, max_attempts, e)
            if attempt == max_attempts:
                return None

def get_coordinates_from_location(location: str):
    if not location:
        return None, None

    params = {
        "q": location,
        "key": OPENCAGE_API_KEY,
        "language": "en",
        "limit": 5,
        "countrycode": "pt",
        "no_annotations": 1,
    }

    try:
        response = requests.get("https://api.opencagedata.com/geocode/v1/json", params=params, timeout=15)
        response.raise_for_status()
    except Exception as exc:
        logger.error("❌ Ошибка запроса координат для '%s': %s", location, exc)
        return None, None

    data = response.json()
    results = data.get("results", [])
    for result in results:
        components = result.get("components", {})
        if components.get("country_code") != "pt":
            continue
        geometry = result.get("geometry", {})
        lat = geometry.get("lat")
        lon = geometry.get("lng")
        if lat is not None and lon is not None:
            return lat, lon

    logger.warning("⚠️ Не удалось найти координаты в Португалии для '%s'", location)
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

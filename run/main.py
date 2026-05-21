# С этим файлом будем работать

import os
import logging
import time
import json
import socket
import openai
import requests
from datetime import datetime, timedelta
import pytz

# Настройки логирования


def _resolve_log_level(value: str | int | None) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        name = value.strip().upper()
        candidate = getattr(logging, name, None)
        if isinstance(candidate, int):
            return candidate
        try:
            return int(name)
        except ValueError:
            return logging.INFO
    return logging.INFO


LOG_LEVEL = _resolve_log_level(os.getenv("LOG_LEVEL", "INFO"))
LOG_FILE = os.getenv("LOG_FILE", "/app/logs/automation.log")

# Настройки из переменных окружения
SKIP_AI = os.getenv('SKIP_AI', 'false').lower() == 'true'
SKIP_IMAGE = os.getenv('SKIP_IMAGE', 'true').lower() == 'true'
RUN_ON_STARTUP = os.getenv('RUN_ON_STARTUP', 'true').lower() == 'true'
SCHEDULED_HOUR = int(os.getenv('SCHEDULED_HOUR', '2'))
SCHEDULED_MINUTE = int(os.getenv('SCHEDULED_MINUTE', '0'))
TIMEZONE = os.getenv('TIMEZONE', 'Europe/Moscow')
PT_RETRY_ATTEMPTS = int(os.getenv('PT_RETRY_ATTEMPTS', '2'))
TELEGRAM_NOTIFICATIONS_ENABLED = os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false").lower() == "true"
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "racefinder_telethon")
TELEGRAM_TARGET = os.getenv("TELEGRAM_TARGET", "")

STATUS_REVISED_INCOMPLETE = "Revised (incomplete)"
STATUS_REVISED_COMPLETE = "Revised (complete)"
STATUS_PUBLISHED = "Published"
STATUS_PUBLISHED_INCOMPLETE = "Published (incomplete)"

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=LOG_LEVEL, format=_LOG_FORMAT)
if LOG_FILE:
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(LOG_LEVEL)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logging.getLogger().addHandler(file_handler)
    except Exception as exc:
        logging.warning("⚠️ Не удалось настроить лог-файл %s: %s", LOG_FILE, exc)

from _1_google_loader import (
    load_config,
    load_all_rows,
    batch_update_cells
)

from _2_content_generation import (
    extract_text_from_url,
    build_first_assistant_prompt,
    validate_source_texts,
    normalize_regulations_link_block,
    call_openai_assistant,
    call_second_openai_assistant,
    generate_image,
    get_coordinates_with_city_fallback,
    translate_title_to_en
)

from _3_create_product import (
    create_or_update_product as create_product_pt_primary,
    get_category_id_by_name,
    get_category_translation_id,
    ensure_category_translation,
)
from _4_create_translation import create_or_update_product_pt as create_product_pt
from _5_taxonomy_and_attributes import assign_attributes_to_product
from _6_create_variations import sync_variations_by_ids
from utils import (
    normalize_attribute_payload,
    normalize_category_pairs,
    parse_subcategory_values,
    get_missing_pt_fields,
    normalize_attribute_name,
)
from website_snapshot import (
    compute_website_hash,
    has_website_changed,
    send_telegram_notification,
)

# Обратная совместимость для тестов/моков со старым именем.
create_product_en = create_product_pt_primary


def log_network_diagnostics():
    try:
        with open("/etc/resolv.conf", "r", encoding="utf-8") as resolv_file:
            resolv_lines = [line.strip() for line in resolv_file if line.strip()]
        preview = " | ".join(resolv_lines[:5])
        logging.info("🕵️ DNS resolv.conf: %s", preview)
    except Exception as exc:
        logging.warning("⚠️ Не удалось прочитать /etc/resolv.conf: %s", exc)

    for host in ("oauth2.googleapis.com", "api.opencagedata.com", "api.openai.com"):
        try:
            infos = socket.getaddrinfo(host, None)
            addresses = sorted({info[4][0] for info in infos if info[4]})
            logging.info("🌐 DNS %s -> %s", host, ", ".join(addresses))
        except socket.gaierror as exc:
            logging.error("❌ DNS %s: %s", host, exc)
        except Exception as exc:  # noqa: BLE001
            logging.warning("⚠️ Ошибка диагностики DNS для %s: %s", host, exc)

def collect_all_attributes(variations):
    all_attributes = {}
    for var in variations:
        for attr in var["attributes"]:
            name = normalize_attribute_name(attr["name"])
            value = attr["option"]
            if name not in all_attributes:
                all_attributes[name] = set()
            all_attributes[name].add(value)
    return {k: list(v) for k, v in all_attributes.items()}


def _cell_value_as_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _write_variation_ids_to_sheet(row_to_variation_id: dict, column_name: str, headers: dict):
    if column_name not in headers:
        logging.warning("⚠️ Колонка '%s' не найдена в Google Sheets, ID вариаций не будут сохранены.", column_name)
        return
    for target_row_index, variation_id in row_to_variation_id.items():
        batch_update_cells(target_row_index, {column_name: str(variation_id)}, headers)


def _norm_category_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _load_category_root_map() -> dict[str, dict[str, int]]:
    raw = os.getenv("CATEGORY_ROOT_MAP_JSON", "").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    result = {}
    for key, value in parsed.items():
        if not isinstance(value, dict):
            continue
        en_id = int(value.get("en_parent_id") or 0)
        pt_id = int(value.get("pt_parent_id") or 0)
        if en_id and pt_id:
            result[_norm_category_key(key)] = {"en_parent_id": en_id, "pt_parent_id": pt_id}
    return result


def _build_pt_category_ids_from_en(row: dict) -> list[dict]:
    categories_raw = []
    main_category = row.get("CATEGORY")
    main_subcategory = row.get("SUBCATEGORY")
    if main_category:
        categories_raw.append((main_category, main_subcategory))
    extra_cats = row.get("extra_categories")
    if isinstance(extra_cats, (list, set, tuple)):
        for item in extra_cats:
            if isinstance(item, (list, tuple)) and len(item) == 2 and item[0]:
                categories_raw.append((item[0], item[1]))

    normalized_pairs = normalize_category_pairs(categories_raw)
    logging.debug("🧭 CATEGORY MAP INPUT (row_id=%s): raw=%s normalized=%s", row.get("ID"), categories_raw, normalized_pairs)

    root_map = _load_category_root_map()
    category_ids = []
    seen = set()
    for parent_name, child_name in normalized_pairs:
        logging.debug("🧭 CATEGORY PAIR START (row_id=%s): parent='%s' child='%s'", row.get("ID"), parent_name, child_name)
        root_key = _norm_category_key(parent_name)
        mapped = root_map.get(root_key)
        if not mapped:
            raise RuntimeError(
                f"CATEGORY '{parent_name}' отсутствует в CATEGORY_ROOT_MAP_JSON. "
                f"Публикация ID={row.get('ID')} остановлена."
            )
        en_parent_id = mapped["en_parent_id"]
        logging.debug("🧭 CATEGORY EN parent resolved (row_id=%s): '%s' -> %s", row.get("ID"), parent_name, en_parent_id)
        pt_parent_id = mapped["pt_parent_id"]
        logging.debug("🧭 CATEGORY PT parent translation (row_id=%s): en_parent_id=%s -> pt_parent_id=%s", row.get("ID"), en_parent_id, pt_parent_id)
        if pt_parent_id and pt_parent_id not in seen:
            category_ids.append({"id": pt_parent_id})
            seen.add(pt_parent_id)
            logging.debug("🧭 CATEGORY ADD parent (row_id=%s): pt_parent_id=%s", row.get("ID"), pt_parent_id)
        elif pt_parent_id in seen:
            logging.debug("🧭 CATEGORY DUP parent ignored (row_id=%s): pt_parent_id=%s", row.get("ID"), pt_parent_id)
        else:
            logging.warning("🧭 CATEGORY SKIP parent translation missing (row_id=%s): en_parent_id=%s name='%s'", row.get("ID"), en_parent_id, parent_name)
        if child_name:
            en_child_id = get_category_id_by_name(child_name, parent_id=en_parent_id, lang="en")
            if not en_child_id:
                raise RuntimeError(
                    f"Не удалось найти/создать EN child '{child_name}' под parent_id={en_parent_id} "
                    f"(ID={row.get('ID')})."
                )
            logging.debug(
                "🧭 CATEGORY EN child resolved (row_id=%s): '%s' under parent_id=%s -> child_id=%s",
                row.get("ID"), child_name, en_parent_id, en_child_id
            )
            pt_child_id = get_category_translation_id(en_child_id, "pt")
            logging.debug(
                "🧭 CATEGORY PT child translation (row_id=%s): en_child_id=%s -> pt_child_id=%s",
                row.get("ID"), en_child_id, pt_child_id
            )
            if not pt_child_id:
                try:
                    pt_child_id = ensure_category_translation(
                        en_child_id,
                        source_lang="en",
                        target_lang="pt",
                        target_parent_id=pt_parent_id,
                    )
                    logging.info(
                        "🧭 CATEGORY PT child translation created (row_id=%s): en_child_id=%s -> pt_child_id=%s",
                        row.get("ID"), en_child_id, pt_child_id
                    )
                except Exception as exc:
                    logging.warning(
                        "🧭 CATEGORY PT child translation create failed (row_id=%s): en_child_id=%s error=%s",
                        row.get("ID"), en_child_id, exc
                    )
            if pt_child_id and pt_child_id not in seen:
                category_ids.append({"id": pt_child_id})
                seen.add(pt_child_id)
                logging.debug("🧭 CATEGORY ADD child (row_id=%s): pt_child_id=%s", row.get("ID"), pt_child_id)
            elif pt_child_id in seen:
                logging.debug("🧭 CATEGORY DUP child ignored (row_id=%s): pt_child_id=%s", row.get("ID"), pt_child_id)
            else:
                logging.warning(
                    "🧭 CATEGORY SKIP child translation missing (row_id=%s): en_child_id=%s child='%s'",
                    row.get("ID"), en_child_id, child_name
                )
    logging.debug("🧭 CATEGORY MAP RESULT (row_id=%s): pt_category_ids=%s", row.get("ID"), category_ids)
    return category_ids


def get_next_run_time():
    """Вычисляет время следующего запуска по расписанию"""
    moscow_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(moscow_tz)
    
    # Создаем время запуска на сегодня
    scheduled_time = now.replace(hour=SCHEDULED_HOUR, minute=SCHEDULED_MINUTE, second=0, microsecond=0)
    
    # Если время уже прошло сегодня, планируем на завтра
    if now >= scheduled_time:
        scheduled_time += timedelta(days=1)
    
    return scheduled_time

def wait_until_next_run():
    """Ожидает до времени следующего запуска"""
    next_run = get_next_run_time()
    moscow_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(moscow_tz)
    
    wait_seconds = (next_run - now).total_seconds()
    logging.info(f"⏰ Следующий запуск запланирован на {next_run.strftime('%Y-%m-%d %H:%M:%S')} МСК")
    logging.info(f"⏳ Ожидание {wait_seconds:.0f} секунд...")
    
    time.sleep(wait_seconds)

def run_automation():
    """Основная функция автоматизации"""
    logging.info("🚀 Запуск автоматизации обработки данных")

    log_network_diagnostics()

    config = load_config()

    # Пытаемся загрузить строки с несколькими быстрыми повторами при сетевых сбоях
    max_attempts = 3
    delay_sec = 10
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            rows, headers = load_all_rows()
            break
        except Exception as e:
            last_error = e
            logging.warning(f"⚠️ Не удалось загрузить строки из Google Sheets (попытка {attempt}/{max_attempts}): {e}")
            if attempt < max_attempts:
                logging.info(f"⏳ Повторная попытка через {delay_sec} сек...")
                time.sleep(delay_sec)
    else:
        # Если все попытки исчерпаны — пробрасываем исключение, чтобы обработать выше и запланировать быстрый повтор
        raise last_error

    changed_websites = []

    for i, (row_index, row) in enumerate(rows):
        status_raw = row.get("STATUS", "").strip()
        status = status_raw.lower()
        row_id = row.get("ID", "unknown")

        logging.debug(f"Строка {row_index}: ID={row_id}, STATUS='{row.get('STATUS', '')}' -> '{status}'")

        if status in (
            STATUS_REVISED_INCOMPLETE.lower(),
            STATUS_REVISED_COMPLETE.lower(),
        ):
            is_incomplete = status == STATUS_REVISED_INCOMPLETE.lower()
            logging.info(f"📌 Обработка {row.get('STATUS')} (ID={row.get('ID')})")

            try:
                # --- 1. Подготовка данных ---
                lat, lon = get_coordinates_with_city_fallback(
                    row.get("LOCATION", ""),
                    row.get("LOCATION (CITY)", "")
                )
                row["LAT"] = lat if lat is not None else ""
                row["LON"] = lon if lon is not None else ""

                # Для incomplete и complete публикуем EN-название: переводим PT -> EN перед созданием/обновлением WP.
                pt_title = row.get("RACE NAME (PT)", "").strip()
                translated_title = translate_title_to_en(pt_title)
                if translated_title:
                    row["RACE NAME"] = translated_title
                    batch_update_cells(row_index, {"RACE NAME": row["RACE NAME"]}, headers)

                if status in (
                    STATUS_REVISED_INCOMPLETE.lower(),
                    STATUS_REVISED_COMPLETE.lower(),
                ):
                    website_text, _ = extract_text_from_url(row.get("WEBSITE", ""))

                    regulations_url = row.get("REGULATIONS", "")
                    regulations_text, pdf_path = "", None
                    file_ids = []
                    if regulations_url:
                        regulations_text, pdf_path = extract_text_from_url(regulations_url)
                        if pdf_path:
                            with open(pdf_path, "rb") as f:
                                upload_response = openai.files.create(file=f, purpose="assistants")
                            file_ids.append(upload_response.id)

                    errors = validate_source_texts(
                        website_url=row.get("WEBSITE", ""),
                        website_text=website_text,
                        regulations_url=regulations_url,
                        regulations_text=regulations_text,
                        regulations_pdf_path=pdf_path
                    )
                    if errors:
                        status_message = "Error: " + "; ".join(errors)
                        logging.error("❌ Не удалось получить источники: %s", status_message)
                        batch_update_cells(row_index, {"STATUS": status_message}, headers)
                        continue

                    combined_text = build_first_assistant_prompt(
                        regulations_url=regulations_url,
                        regulations_text=regulations_text,
                        website_text=website_text
                    )
                    if not combined_text.strip():
                        raise Exception("Нет текста для GPT")

                    if SKIP_AI:
                        logging.info("🤖 SKIP_AI=true, используем заглушки")
                        result = {
                            "summary": "Заглушка summary",
                            "org_info": "Заглушка org_info",
                            "benefits": "Заглушка benefits",
                            "faq": "",
                            "summary_pt": "Заглушка summary_pt",
                            "org_info_pt": "Заглушка org_info_pt",
                            "benefits_pt": "Заглушка benefits_pt",
                            "faq_pt": "",
                            "image_prompt": "Placeholder image"
                        }
                    else:
                        first_result = call_openai_assistant(combined_text, file_ids=file_ids)
                        if first_result is None:
                            logging.error("❌ Первый ассистент не вернул результат")
                            continue

                        logging.info("✅ Первый ассистент завершил работу, передаём результат во второй ассистент")
                        first_result = normalize_regulations_link_block(first_result, regulations_url)
                        regulations_hint = f"REGULATIONS LINK: {regulations_url if regulations_url else '(empty)'}"
                        result = None
                        missing_pt_fields = []
                        total_attempts = 1 + max(0, PT_RETRY_ATTEMPTS)
                        for attempt in range(total_attempts):
                            result = call_second_openai_assistant(first_result, regulations_hint=regulations_hint)
                            if result is None:
                                logging.error("❌ Второй ассистент не вернул результат")
                                continue
                            missing_pt_fields = get_missing_pt_fields(result)
                            if not missing_pt_fields:
                                break
                            logging.warning(
                                f"⚠️ Во втором ассистенте нет PT-переводов для {', '.join(missing_pt_fields)} "
                                f"(попытка {attempt + 1}/{total_attempts})"
                            )

                        if result is None:
                            logging.error("❌ Второй ассистент не вернул результат после повторов")
                            continue
                        if missing_pt_fields:
                            status_message = f"Error: missing PT fields ({', '.join(missing_pt_fields)})"
                            logging.error(f"❌ {status_message}")
                            batch_update_cells(row_index, {"STATUS": status_message}, headers)
                            continue

                    if SKIP_IMAGE or SKIP_AI:
                        image_info = {"url": "https://dev.racefinder.pt/wp-content/uploads/2025/07/img-placeholder.png", "id": None}
                    else:
                        image_info = generate_image(result["image_prompt"])

                    row.update({
                        "SUMMARY": result.get("summary", ""),
                        "ORG INFO": result.get("org_info", ""),
                        "BENEFITS": "\n".join(result["benefits"]) if isinstance(result.get("benefits"), list) else result.get("benefits", ""),
                        "FAQ": result.get("faq", ""),
                        "IMAGE URL": image_info.get("url", ""),
                        "IMAGE ID": image_info.get("id", ""),
                        "SUMMARY (PT)": result.get("summary_pt", ""),
                        "ORG INFO (PT)": result.get("org_info_pt", ""),
                        "BENEFITS (PT)": "\n".join(result["benefits_pt"]) if isinstance(result.get("benefits_pt"), list) else result.get("benefits_pt", ""),
                        "FAQ (PT)": result.get("faq_pt", ""),
                        "LAT": row["LAT"],
                        "LON": row["LON"],
                        "RACE NAME (PT)": row.get("RACE NAME (PT)", ""),
                        "image_id": image_info.get("id", None)
                    })

                    batch_update_cells(row_index, {
                        "SUMMARY": row["SUMMARY"],
                        "ORG INFO": row["ORG INFO"],
                        "BENEFITS": row["BENEFITS"],
                        "FAQ": row["FAQ"],
                        "IMAGE URL": row["IMAGE URL"],
                        "SUMMARY (PT)": row["SUMMARY (PT)"],
                        "ORG INFO (PT)": row["ORG INFO (PT)"],
                        "BENEFITS (PT)": row["BENEFITS (PT)"],
                        "FAQ (PT)": row["FAQ (PT)"],
                        "RACE NAME (PT)": row["RACE NAME (PT)"],
                        "RACE NAME": row.get("RACE NAME", "")
                    }, headers)
                    if "IMAGE ID" in headers:
                        batch_update_cells(row_index, {"IMAGE ID": row["IMAGE ID"]}, headers)

                # --- 2. Собираем атрибуты и первую вариацию ---
                last_main_row = row.copy()
                last_main_attributes = {}
                last_main_row["extra_categories"] = set()
                main_category = row.get("CATEGORY")
                main_subcategory = row.get("SUBCATEGORY")
                if main_category:
                    subcategories = parse_subcategory_values(main_subcategory)
                    if subcategories:
                        for subcategory in subcategories:
                            last_main_row["extra_categories"].add((main_category, subcategory))
                    else:
                        last_main_row["extra_categories"].add((main_category, None))
                if row.get("ATTRIBUTE") and row.get("VALUE"):
                    last_main_attributes[normalize_attribute_name(row["ATTRIBUTE"])] = row["VALUE"]

                for attr_name, col in [
                    ("Distance", "DISTANCE"),
                    ("Team", "TEAM"),
                    ("Type", "TYPE"),
                    ("License", "LICENSE"),
                    ("Race Start Date", "RACE START DATE"),
                    ("Race Start Time", "RACE START TIME")
                ]:
                    if row.get(col):
                        last_main_attributes[attr_name] = row[col]

                variation_attributes = [{"name": k, "option": v} for k, v in last_main_attributes.items()]
                variation_entries_en = [{
                    "row_index": row_index,
                    "existing_variation_id": _cell_value_as_str(row.get("WP VARIATION ID EN", "")),
                    "regular_price": str(row.get("PRICE", "0")),
                    "attributes": variation_attributes,
                }]
                variation_entries_pt = [{
                    "row_index": row_index,
                    "existing_variation_id": _cell_value_as_str(row.get("WP VARIATION ID PT", "")),
                    "regular_price": str(row.get("PRICE", "0")),
                    "attributes": variation_attributes,
                }]

                # --- 3. Собираем подвариации ---
                for j in range(i + 1, len(rows)):
                    sub_row_index, sub_row = rows[j]
                    sub_status = sub_row.get("STATUS", "").strip().lower()
                    if sub_status in (
                        STATUS_REVISED_INCOMPLETE.lower(),
                        STATUS_REVISED_COMPLETE.lower(),
                        STATUS_PUBLISHED.lower(),
                        STATUS_PUBLISHED_INCOMPLETE.lower(),
                    ):
                        break
                    if sub_status == "":
                        var_attrs = []
                        if sub_row.get("ATTRIBUTE") and sub_row.get("VALUE"):
                            var_attrs.append({"name": normalize_attribute_name(sub_row["ATTRIBUTE"]), "option": sub_row["VALUE"]})
                        for attr_name, col in [
                            ("Distance", "DISTANCE"),
                            ("Team", "TEAM"),
                            ("Type", "TYPE"),
                            ("License", "LICENSE"),
                            ("Race Start Date", "RACE START DATE"),
                            ("Race Start Time", "RACE START TIME")
                        ]:
                            if sub_row.get(col):
                                var_attrs.append({"name": attr_name, "option": sub_row[col]})
                        if var_attrs:
                            variation_entries_en.append({
                                "row_index": sub_row_index,
                                "existing_variation_id": _cell_value_as_str(sub_row.get("WP VARIATION ID EN", "")),
                                "regular_price": str(sub_row.get("PRICE", "0")),
                                "attributes": var_attrs,
                            })
                            variation_entries_pt.append({
                                "row_index": sub_row_index,
                                "existing_variation_id": _cell_value_as_str(sub_row.get("WP VARIATION ID PT", "")),
                                "regular_price": str(sub_row.get("PRICE", "0")),
                                "attributes": var_attrs,
                            })
                    else:
                        break

                # --- 4. Публикация в WooCommerce ---
                # EN category names from sheet are treated as source of truth; PT categories are resolved via WPML translations.
                last_main_row["CATEGORY_IDS_PT"] = _build_pt_category_ids_from_en(last_main_row)
                lat, lon = get_coordinates_with_city_fallback(
                    last_main_row.get("LOCATION", ""),
                    last_main_row.get("LOCATION (CITY)", "")
                )
                last_main_row["LAT"] = lat if lat is not None else ""
                last_main_row["LON"] = lon if lon is not None else ""
                last_main_row["extra_categories"] = [
                    (cat, sub_cat)
                    for cat, sub_cat in last_main_row.get("extra_categories", set())
                    if cat
                ]

                existing_pt_product_id = _cell_value_as_str(row.get("WP PRODUCT ID PT", "")) if not is_incomplete else ""
                pt_product_id = create_product_pt_primary(
                    last_main_row,
                    existing_product_id=existing_pt_product_id or None
                )
                last_main_row["pt_product_id"] = pt_product_id

                # Получаем slug
                try:
                    r = requests.get(f"{config['wp_url']}/wp-json/wc/v3/products/{pt_product_id}",
                                     auth=(config["consumer_key"], config["consumer_secret"]))
                    r.raise_for_status()
                    data = r.json()
                    slug = data.get("slug", "")
                    permalink = data.get("permalink", "")
                    if permalink:
                        last_main_row["LINK RACEFINDER"] = permalink
                    elif slug:
                        last_main_row["LINK RACEFINDER"] = f"https://dev.racefinder.pt/event/{slug}"
                    else:
                        last_main_row["LINK RACEFINDER"] = ""
                except Exception as e:
                    logging.error(f"Slug error: {e}")
                    last_main_row["LINK RACEFINDER"] = ""

                attr_payload = normalize_attribute_payload(last_main_attributes)
                for var in variation_entries_en:
                    for attr in var["attributes"]:
                        attr_name = normalize_attribute_name(attr.get("name", ""))
                        attr_option = str(attr.get("option", "")).strip()
                        if not attr_name or not attr_option:
                            continue
                        if attr_name not in attr_payload:
                            attr_payload[attr_name] = []
                        elif not isinstance(attr_payload[attr_name], list):
                            attr_payload[attr_name] = [attr_payload[attr_name]]
                        if attr_option not in attr_payload[attr_name]:
                            attr_payload[attr_name].append(attr_option)

                assign_attributes_to_product(pt_product_id, attr_payload, lang="pt")
                pt_row_to_variation_id = sync_variations_by_ids(pt_product_id, variation_entries_pt, lang="pt")

                existing_en_product_id = _cell_value_as_str(row.get("WP PRODUCT ID EN", "")) if not is_incomplete else ""
                en_product_id = create_product_pt(
                    last_main_row,
                    pt_product_id,
                    attributes=attr_payload,
                    last_variations=variation_entries_en,
                    config=config,
                    existing_pt_product_id=existing_en_product_id or None
                )
                last_main_row["en_product_id"] = en_product_id
                en_row_to_variation_id = sync_variations_by_ids(en_product_id, variation_entries_en, lang="en")

                # Final hard reconcile pass for BOTH langs.
                # Keep only variations represented by current sheet block, then persist definitive IDs.
                en_row_to_variation_id = sync_variations_by_ids(en_product_id, variation_entries_en, lang="en")
                _write_variation_ids_to_sheet(en_row_to_variation_id, "WP VARIATION ID EN", headers)

                pt_row_to_variation_id = sync_variations_by_ids(pt_product_id, variation_entries_pt, lang="pt")
                _write_variation_ids_to_sheet(pt_row_to_variation_id, "WP VARIATION ID PT", headers)

                snapshot_hash = ""
                if is_incomplete:
                    snapshot_hash, _ = compute_website_hash(row.get("WEBSITE", ""))

                # --- 5. Обновление статуса в таблице ---
                batch_update_cells(row_index, {
                    "STATUS": STATUS_PUBLISHED_INCOMPLETE if is_incomplete else STATUS_PUBLISHED,
                    "LINK RACEFINDER": last_main_row.get("LINK RACEFINDER", ""),
                    "WP PRODUCT ID EN": en_product_id or "",
                    "WP PRODUCT ID PT": pt_product_id or "",
                    "WEBSITE SNAPSHOT HASH": snapshot_hash
                }, headers)

                logging.info(
                    "✅ Published ID=%s EN=%s PT=%s MODE=%s",
                    row.get("ID"),
                    en_product_id,
                    pt_product_id,
                    "incomplete" if is_incomplete else "complete"
                )

            except Exception as e:
                logging.exception(f"❌ Ошибка при обработке Revised ID={row.get('ID')}")
                continue

        elif status == STATUS_PUBLISHED_INCOMPLETE.lower():
            website_url = (row.get("WEBSITE", "") or "").strip()
            previous_hash = (row.get("WEBSITE SNAPSHOT HASH", "") or "").strip()
            if not previous_hash or not website_url:
                logging.debug("⏭ Пропуск мониторинга Published (incomplete): нет WEBSITE SNAPSHOT HASH или WEBSITE (ID=%s)", row.get("ID"))
                continue

            try:
                changed, current_hash = has_website_changed(previous_hash, website_url)
            except Exception as exc:
                logging.warning("⚠️ Не удалось загрузить WEBSITE для мониторинга (ID=%s): %s", row.get("ID"), exc)
                continue

            updates = {
                "LAST DIFF CHECK AT": datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S"),
            }
            if changed:
                logging.info("🔔 Изменения WEBSITE обнаружены для ID=%s", row.get("ID"))
                changed_websites.append(
                    {
                        "id": str(row.get("ID", "")).strip(),
                        "race": str(row.get("RACE NAME", "")).strip(),
                        "url": website_url,
                    }
                )
            batch_update_cells(row_index, updates, headers)
            continue

        elif status == STATUS_PUBLISHED.lower():
            logging.debug(f"⏭ Пропуск Published (ID={row.get('ID')})")
            continue

    if TELEGRAM_NOTIFICATIONS_ENABLED and changed_websites:
        lines = ["Website changes detected", ""]
        for item in changed_websites[:100]:
            lines.append(f"- ID: {item['id']} | Race: {item['race']} | URL: {item['url']}")
        if len(changed_websites) > 100:
            lines.append(f"... and {len(changed_websites) - 100} more")
        message = "\n".join(lines)
        sent = send_telegram_notification(
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            TELEGRAM_SESSION_NAME,
            TELEGRAM_TARGET,
            message
        )
        if not sent:
            logging.warning("⚠️ Не удалось отправить агрегированное Telegram-уведомление (%s изменений).", len(changed_websites))

def main():
    """Основная функция с расписанием"""
    moscow_tz = pytz.timezone(TIMEZONE)
    now = datetime.now(moscow_tz)
    
    logging.info(f"🕐 Текущее время: {now.strftime('%Y-%m-%d %H:%M:%S')} МСК")
    logging.info(f"⚙️ Настройки: RUN_ON_STARTUP={RUN_ON_STARTUP}, SCHEDULED_HOUR={SCHEDULED_HOUR}:{SCHEDULED_MINUTE:02d}")
    
    # Тестовый запуск при старте контейнера (если включен)
    if RUN_ON_STARTUP:
        logging.info("🚀 Тестовый запуск при старте контейнера")
        try:
            run_automation()
            logging.info("✅ Тестовый запуск завершен успешно")
        except Exception as e:
            logging.exception("❌ Ошибка при тестовом запуске")
    
    # Основной цикл с расписанием
    while True:
        # Ожидание до следующего запуска
        wait_until_next_run()

        try:
            # Запуск по расписанию
            logging.info("🔄 Запуск по расписанию")
            run_automation()
            logging.info("✅ Запуск по расписанию завершен успешно")

        except Exception as e:
            logging.exception("❌ Ошибка при запуске по расписанию")
            # Если ошибка носит сетевой характер — делаем быстрый повтор через 15 минут, не откладывая на сутки
            quick_retry_minutes = 15
            logging.info(f"⏳ Быстрый повтор через {quick_retry_minutes} минут...")
            time.sleep(quick_retry_minutes * 60)
            try:
                logging.info("🔄 Быстрый повтор запуска по расписанию")
                run_automation()
                logging.info("✅ Быстрый повтор завершен успешно")
            except Exception:
                logging.exception("❌ Быстрый повтор завершился ошибкой. Ожидаем следующего планового запуска.")

if __name__ == "__main__":
    main()

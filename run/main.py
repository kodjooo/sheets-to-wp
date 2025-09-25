# С этим файлом будем работать

SKIP_AI = False     # пропускает вызовы OpenAI GPT, генерацию текста и картинок
SKIP_IMAGE = True   # пропускает только генерацию картинок

import logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
import time
import json
import openai
import requests

from _1_google_loader import (
    load_config,
    load_revised_rows,
    load_all_rows,
    update_status_to_published,
    batch_update_cells
)

from _2_content_generation import (
    extract_text_from_url,
    call_openai_assistant,
    generate_image,
    get_coordinates_from_location,
    translate_title_to_pt
)

from _3_create_product import create_product as create_product_en
from _3_create_product import get_category_id_by_name
from _4_create_translation import create_product_pt as create_product_pt
from _5_taxonomy_and_attributes import assign_attributes_to_product
from _6_create_variations import create_variations

def collect_all_attributes(variations):
    all_attributes = {}
    for var in variations:
        for attr in var["attributes"]:
            name = attr["name"]
            value = attr["option"]
            if name not in all_attributes:
                all_attributes[name] = set()
            all_attributes[name].add(value)
    return {k: list(v) for k, v in all_attributes.items()}

def main():
    config = load_config()
    rows, headers = load_all_rows()

    last_main_row = None
    last_main_row_index = None
    last_main_attributes = {}
    last_variations = []

    for i, (row_index, row) in enumerate(rows):
        status = row.get("STATUS", "").strip().lower()

        # Если нашли главную строку Revised
        if status == "revised":
            logging.info(f"📌 Обработка Revised (ID={row.get('ID')})")

            try:
                # --- 1. Генерация данных (GPT + картинка) ---
                lat, lon = get_coordinates_from_location(row.get("LOCATION", ""))
                row["LAT"] = lat if lat is not None else ""
                row["LON"] = lon if lon is not None else ""

                website_text, website_pdf_path = extract_text_from_url(row.get("WEBSITE", ""))
                original_title = row.get("RACE NAME", "").strip()
                translated_title = translate_title_to_pt(original_title)
                if translated_title:
                    row["RACE NAME (PT)"] = translated_title

                regulations_url = row.get("REGULATIONS", "")
                regulations_text, pdf_path = "", None
                file_ids = []
                if regulations_url:
                    regulations_text, pdf_path = extract_text_from_url(regulations_url)
                    if pdf_path:
                        with open(pdf_path, "rb") as f:
                            upload_response = openai.files.create(file=f, purpose="assistants")
                        file_ids.append(upload_response.id)

                has_pdf = bool(file_ids)
                combined_text = ""
                if regulations_url:
                    combined_text += f"\n\nREGULATIONS LINK:\n{regulations_url}"
                if regulations_text:
                    combined_text += f"\n\nREGULATIONS INFO:\n{regulations_text}"
                combined_text += f"\n\nWEBSITE INFO:\n{website_text}"

                if not combined_text.strip():
                    raise Exception("Нет текста для GPT")

                if SKIP_AI:
                    result = {
                        "summary": "Заглушка summary",
                        "org_info": "Заглушка org_info",
                        "benefits": "Заглушка benefits",
                        "summary_pt": "Заглушка summary_pt",
                        "org_info_pt": "Заглушка org_info_pt",
                        "benefits_pt": "Заглушка benefits_pt",
                        "image_prompt": "Placeholder image"
                    }
                else:
                    result = call_openai_assistant(
                        combined_text,
                        file_ids=file_ids if has_pdf else None,
                        has_pdf=has_pdf
                    )

                # Генерация картинки
                if SKIP_IMAGE or SKIP_AI:
                    image_info = {"url": "https://dev.racefinder.pt/wp-content/uploads/2025/07/img-placeholder.png", "id": None}
                else:
                    image_info = generate_image(result["image_prompt"])

                row.update({
                    "SUMMARY": result.get("summary", ""),
                    "ORG INFO": result.get("org_info", ""),
                    "BENEFITS": "\n".join(result["benefits"]) if isinstance(result.get("benefits"), list) else result.get("benefits", ""),
                    "IMAGE URL": image_info.get("url", ""),
                    "IMAGE ID": image_info.get("id", ""),
                    "SUMMARY (PT)": result.get("summary_pt", ""),
                    "ORG INFO (PT)": result.get("org_info_pt", ""),
                    "BENEFITS (PT)": "\n".join(result["benefits_pt"]) if isinstance(result.get("benefits_pt"), list) else result.get("benefits_pt", ""),
                    "LAT": row["LAT"],
                    "LON": row["LON"],
                    "RACE NAME (PT)": row.get("RACE NAME (PT)", ""),
                    "image_id": image_info.get("id", None)
                })

                # 📤 Сохраняем сгенерированные данные в таблицу
                batch_update_cells(row_index, {
                    "SUMMARY": row["SUMMARY"],
                    "ORG INFO": row["ORG INFO"],
                    "BENEFITS": row["BENEFITS"],
                    "IMAGE URL": row["IMAGE URL"],
                    "IMAGE ID": row["IMAGE ID"],
                    "SUMMARY (PT)": row["SUMMARY (PT)"],
                    "ORG INFO (PT)": row["ORG INFO (PT)"],
                    "BENEFITS (PT)": row["BENEFITS (PT)"],
                    "RACE NAME (PT)": row["RACE NAME (PT)"]
                }, headers)

                # --- 2. Собираем атрибуты и первую вариацию ---
                last_main_row = row.copy()
                last_main_row_index = row_index
                last_main_attributes = {}
                if row.get("ATTRIBUTE") and row.get("VALUE"):
                    last_main_attributes[row["ATTRIBUTE"]] = row["VALUE"]
                    last_main_row["extra_categories"] = {(row["ATTRIBUTE"], row["VALUE"])}

                for attr_name, col in [
                    ("Distance", "DISTANCE"),
                    ("Team", "TEAM"),
                    ("License", "LICENSE"),
                    ("Race Start Date", "RACE START DATE"),
                    ("Race Start Time", "RACE START TIME")
                ]:
                    if row.get(col):
                        last_main_attributes[attr_name] = row[col]

                variation_attributes = [{"name": k, "option": v} for k, v in last_main_attributes.items()]
                last_variations = [{
                    "regular_price": str(row.get("PRICE", "0")),
                    "attributes": variation_attributes
                }]

                # --- 3. Собираем подвариации ---
                for j in range(i + 1, len(rows)):
                    sub_index, sub_row = rows[j]
                    sub_status = sub_row.get("STATUS", "").strip().lower()
                    if sub_status in ("revised", "published"):
                        break
                    if sub_status == "":
                        var_attrs = []
                        if sub_row.get("ATTRIBUTE") and sub_row.get("VALUE"):
                            var_attrs.append({"name": sub_row["ATTRIBUTE"], "option": sub_row["VALUE"]})
                            last_main_row["extra_categories"].add((sub_row["ATTRIBUTE"], sub_row["VALUE"]))
                        for attr_name, col in [
                            ("Distance", "DISTANCE"),
                            ("Team", "TEAM"),
                            ("License", "LICENSE"),
                            ("Race Start Date", "RACE START DATE"),
                            ("Race Start Time", "RACE START TIME")
                        ]:
                            if sub_row.get(col):
                                var_attrs.append({"name": attr_name, "option": sub_row[col]})
                        if var_attrs:
                            last_variations.append({
                                "regular_price": str(sub_row.get("PRICE", "0")),
                                "attributes": var_attrs
                            })
                    else:
                        break

                # --- 4. Публикация в WooCommerce ---
                lat, lon = get_coordinates_from_location(last_main_row.get("LOCATION", ""))
                last_main_row["LAT"] = lat if lat is not None else ""
                last_main_row["LON"] = lon if lon is not None else ""
                last_main_row["extra_categories"] = list(last_main_row.get("extra_categories", []))

                en_product_id = create_product_en(last_main_row)
                last_main_row["en_product_id"] = en_product_id

                # Получаем slug
                try:
                    r = requests.get(f"{config['wp_url']}/wp-json/wc/v3/products/{en_product_id}",
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

                attr_payload = {k: [v] if isinstance(v, str) else v for k, v in last_main_attributes.items()}
                for var in last_variations:
                    for attr in var["attributes"]:
                        if attr["name"] not in attr_payload:
                            attr_payload[attr["name"]] = []
                        if attr["option"] not in attr_payload[attr["name"]]:
                            attr_payload[attr["name"]].append(attr["option"])

                assign_attributes_to_product(en_product_id, attr_payload)
                create_variations(en_product_id, last_variations)

                pt_product_id = create_product_pt(
                    last_main_row,
                    en_product_id,
                    attributes=attr_payload,
                    last_variations=last_variations,
                    config=config
                )
                last_main_row["pt_product_id"] = pt_product_id

                # --- 5. Обновление статуса в таблице ---
                batch_update_cells(last_main_row_index, {
                    "STATUS": "Published",
                    "LINK RACEFINDER": last_main_row.get("LINK RACEFINDER", "")
                }, headers)

                logging.info(f"✅ Published ID={row.get('ID')} EN={en_product_id} PT={pt_product_id}")

            except Exception as e:
                logging.exception(f"❌ Ошибка при обработке Revised ID={row.get('ID')}")
                continue

        elif status == "published":
            logging.debug(f"⏭ Пропуск Published (ID={row.get('ID')})")
            continue

if __name__ == "__main__":
    main()
Вот содержимое файла README.md, описывающее установку, структуру и запуск автоматизации загрузки событий в WooCommerce с переводами:

⸻

🏃 RaceFinder Automation

Автоматизация загрузки спортивных мероприятий из Google Таблицы в WooCommerce с переводами на два языка (en → pt), изображением, ACF-полями, атрибутами, категориями и вариациями.

⸻

📁 Структура проекта

.
├── _1_google_loader.py              # Работа с Google Sheets
├── _2_content_generation.py        # Генерация текстов и изображений (OpenAI + BeautifulSoup + PDF)
├── _3_create_product.py            # Создание EN-продукта с ACF и изображением
├── _4_create_translation.py        # Создание PT-перевода и связка через WPML
├── _5_taxonomy_and_attributes.py   # Категории и атрибуты (Woo)
├── _6_create_variations.py         # Генерация вариаций
├── main.py                         # Главный управляющий скрипт
├── config.json                     # Конфигурация (ключи API, ID таблицы и др.)
├── google-credentials.json         # Сервисный аккаунт Google для Sheets API
└── requirements.txt                # Список зависимостей


⸻

⚙️ Установка

1. Установи Python 3.10+

Убедись, что установлен pip.

2. Установи зависимости

pip install -r requirements.txt

Содержимое requirements.txt:

openai
gspread
oauth2client
requests
beautifulsoup4
PyMuPDF
Pillow


⸻

🔑 Конфигурация

1. config.json

{
  "openai_api_key": "sk-...",
  "assistant_id": "asst_...",
  "opencage_api_key": "bdd1...",
  "spreadsheet_id": "1yXt14cb...",
  "worksheet_name": "RACES",
  "sleep_seconds": 3
}

2. google-credentials.json

Файл с сервисным аккаунтом от Google Cloud (API для Google Sheets).

⸻

✅ Запуск

python main.py

Скрипт автоматически:
	•	Загружает строки со статусом Revised
	•	Парсит контент по ссылке
	•	Генерирует описания и изображение (через GPT + DALL·E)
	•	Создает товар (EN) в WooCommerce с ACF, изображением и категориями
	•	Создает перевод (PT) и привязывает его через WPML
	•	Присваивает атрибуты и генерирует вариации
	•	Обновляет статус строки на Published

⸻

🧩 Зависимости на стороне WordPress

Обязательно должны быть установлены и активированы:
	•	WooCommerce
	•	ACF PRO
	•	WPML Multilingual CMS
	•	WooCommerce Multilingual & Multicurrency
	•	JWT Authentication for WP REST API
	•	ACF-поля, категории и глобальные атрибуты созданы вручную

⸻

📌 Примечания
	•	Изображения генерируются на основе IMAGE PROMPT с помощью OpenAI API.
	•	Атрибут Distance должен существовать заранее (или будет создан автоматически).
	•	Работает с Google Таблицей по ID, можно поменять ID и имя листа в config.json.
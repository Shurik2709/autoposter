import os
import json
import time
from datetime import datetime, timedelta
import pytz
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials

MOSCOW_TZ = pytz.timezone("Europe/Moscow")
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = "Posts"

POST_DAYS = [0, 2, 4]
POST_TIME = "10:00"

TOV_PROMPT = """Ты — Шанкар Шиллер, основатель студии брендинга Shankara Brand. 12+ лет в маркетинге.

СТИЛЬ:
- На "ты". Экспертно, без заискивания
- Короткие абзацы, никакой воды
- Минимум прилагательных — только факты и инсайты
- Капс только для ключевых смысловых узлов
- ЗАПРЕЩЕНО: "уникальный", "лучший", пустые приветствия

СТРУКТУРА КАЖДОГО ПОСТА:
1. Провокационный заголовок — вопрос или контраст
2. Погружающая мини-история "представь: ты..." (2-4 предложения, читатель внутри ситуации)
3. Объяснение механизма — почему это происходит. Нейронаука и психология простым языком. Человек должен сказать "вот почему это так работает"
4. Раскрытие через метафору или пример из практики
5. Практические тезисы (▫️) — что конкретно делать сегодня, не абстракции
6. Провокационный тест или вопрос читателю
7. CTA — конкретный
8. Подпись: "Студия брендинга Шанкара. Где смыслы важнее шрифтов."

ГЛАВНЫЙ ПРИНЦИП: максимальная полезность. Человек читает и сразу знает что делать иначе."""

TOPICS = [
    "Почему клиенты выбирают дешевле — и как это изменить",
    "3 признака что твой бренд — это просто логотип",
    "Что такое Job To Be Done и почему это меняет всё в маркетинге",
]

def get_sheet():
    creds_data = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

def generate_post(topic, client):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": TOV_PROMPT},
            {"role": "user", "content": f"Напиши пост на тему: {topic}"}
        ],
        temperature=0.85,
        max_tokens=1000,
    )
    return response.choices[0].message.content.strip()

def get_next_dates(count=3):
    now = datetime.now(MOSCOW_TZ)
    dates = []
    current = now.replace(hour=0, minute=0, second=0, microsecond=0)
    while len(dates) < count:
        current += timedelta(days=1)
        if current.weekday() in POST_DAYS:
            h, m = POST_TIME.split(":")
            dates.append(current.replace(hour=int(h), minute=int(m)))
    return dates

def get_next_id(sheet):
    rows = sheet.get_all_values()
    if len(rows) <= 1:
        return 1
    ids = [int(r[0]) for r in rows[1:] if r and r[0].strip().isdigit()]
    return max(ids) + 1 if ids else 1

def run():
    print("Запуск генерации контент-плана...")
    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    sheet = get_sheet()
    dates = get_next_dates(len(TOPICS))
    next_id = get_next_id(sheet)

    for i, topic in enumerate(TOPICS):
        print(f"[{i+1}/{len(TOPICS)}] {topic}")
        text = generate_post(topic, openai_client)
        publish_time = dates[i].strftime("%Y-%m-%d %H:%M")
        row = [str(next_id + i), text, "", publish_time, "TRUE", "TRUE", "FALSE", "pending", ""]
        sheet.append_row(row)
        print(f"  ✓ Добавлен. Публикация: {publish_time}")
        time.sleep(1)

    print(f"\nГотово. Добавлено постов: {len(TOPICS)}")

if __name__ == "__main__":
    run()

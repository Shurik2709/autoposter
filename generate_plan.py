import os
import json
import time
import requests
import tempfile
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = "Posts"
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS"]

IMAGE_PROMPT = """Minimal style, dark background, high contrast.
Abstract conceptual image for social media post about branding and marketing.
No text, no people, no faces. Pure minimalism.
Black, white, and one accent color (gold or deep blue).
Premium, editorial, thoughtful aesthetic."""

IMGUR_CLIENT_ID = "546c25a59c58ad7"


def get_sheet():
    creds_data = json.loads(GOOGLE_CREDENTIALS)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)


def generate_image(text, client):
    desc = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"One sentence in English: what abstract minimalist visual fits a post about: '{text[:200]}'? Only objects/shapes, no text, no people."}],
        max_tokens=100,
    ).choices[0].message.content.strip()

    response = client.images.generate(
        model="dall-e-3",
        prompt=f"{IMAGE_PROMPT} Theme: {desc}",
        size="1024x1024",
        quality="standard",
        n=1,
    )
    return response.data[0].url


def upload_image(image_url):
    img_data = requests.get(image_url, timeout=30).content
    response = requests.post(
        "https://api.imgur.com/3/image",
        headers={"Authorization": f"Client-ID {IMGUR_CLIENT_ID}"},
        data={"image": img_data, "type": "file"},
        timeout=30,
    )
    return response.json()["data"]["link"]


def run():
    print("Проверяю таблицу...")
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    sheet = get_sheet()

    rows = sheet.get_all_values()
    if len(rows) <= 1:
        print("Нет постов.")
        return

    updated = 0
    for i, row in enumerate(rows[1:], start=2):
        if len(row) < 9:
            row += [""] * (9 - len(row))

        status = row[7].strip()
        image_url = row[2].strip()
        text = row[1].strip()

        if status == "pending" and not image_url and text:
            print(f"Строка {i}: генерирую картинку...")
            try:
                dalle_url = generate_image(text, openai_client)
                final_url = upload_image(dalle_url)
                sheet.update_cell(i, 3, final_url)
                print(f"  ✓ Картинка добавлена: {final_url}")
                updated += 1
                time.sleep(3)
            except Exception as e:
                print(f"  ✗ Ошибка: {e}")

    print(f"\nГотово. Обновлено строк: {updated}")


if __name__ == "__main__":
    run()

import os
import json
import time
import requests
import tempfile
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
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


def get_sheet():
    creds_data = json.loads(GOOGLE_CREDENTIALS)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)


def get_drive_service():
    creds_data = json.loads(GOOGLE_CREDENTIALS)
    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    return build("drive", "v3", credentials=creds)


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


def upload_to_drive(image_url, filename, drive_service):
    img_data = requests.get(image_url, timeout=30).content
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(img_data)
        tmp_path = f.name

    file_metadata = {"name": filename}
    media = MediaFileUpload(tmp_path, mimetype="image/png")
    uploaded = drive_service.files().create(
        body=file_metadata, media_body=media, fields="id"
    ).execute()

    file_id = uploaded.get("id")
    drive_service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    os.unlink(tmp_path)
    return f"https://drive.google.com/uc?id={file_id}"


def run():
    print("Проверяю таблицу...")
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    sheet = get_sheet()
    drive_service = get_drive_service()

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
                url = generate_image(text, openai_client)
                filename = f"post_{row[0]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
                drive_url = upload_to_drive(url, filename, drive_service)
                sheet.update_cell(i, 3, drive_url)
                print(f"  ✓ Картинка добавлена: {drive_url}")
                updated += 1
                time.sleep(3)
            except Exception as e:
                print(f"  ✗ Ошибка: {e}")

    print(f"\nГотово. Обновлено строк: {updated}")


if __name__ == "__main__":
    run()

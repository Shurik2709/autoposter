import os
import json
import time
import base64
import requests
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = "Posts"
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]

IMAGE_STYLE = """Style: photorealistic, cinematic, professional photography.
Dark moody atmosphere, dramatic lighting, shallow depth of field, premium editorial look.
NO text, NO people, NO faces, NO logos.
Objects, spaces, textures, or environments only."""


def get_sheet():
    creds_data = json.loads(GOOGLE_CREDENTIALS)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)


def generate_image_prompt(text, client):
    """Читает весь текст поста и создаёт точный визуальный промпт."""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a creative director for a premium branding studio. "
                    "Your task: read the full post text and create a precise visual prompt for a photorealistic image. "
                    "The image must metaphorically reflect the CORE IDEA of the post — not illustrate it literally. "
                    "Think in symbols, textures, environments, objects. "
                    "Output ONLY the image prompt in English, 2-3 sentences max. "
                    "No people, no text, no faces in the image."
                )
            },
            {
                "role": "user",
                "content": f"Post text:\n\n{text}\n\nCreate a photorealistic image prompt that captures the essence of this post."
            }
        ],
        max_tokens=150,
    )
    return response.choices[0].message.content.strip()


def generate_image(text, client):
    image_prompt = generate_image_prompt(text, client)
    print(f"  Промпт для картинки: {image_prompt}")

    response = client.images.generate(
        model="gpt-image-1",
        prompt=f"{IMAGE_STYLE}\n\nScene: {image_prompt}",
        size="1024x1024",
        quality="high",
        n=1,
    )

    image_base64 = response.data[0].b64_json
    return base64.b64decode(image_base64)


def upload_to_github(img_data, filename):
    encoded = base64.b64encode(img_data).decode("utf-8")

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/images/{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "message": f"Add image {filename}",
        "content": encoded,
    }

    response = requests.put(api_url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()

    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/images/{filename}"


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
                img_data = generate_image(text, openai_client)
                filename = f"post_{row[0]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
                final_url = upload_to_github(img_data, filename)
                sheet.update_cell(i, 3, final_url)
                print(f"  ✓ Картинка: {final_url}")
                updated += 1
                time.sleep(3)
            except Exception as e:
                print(f"  ✗ Ошибка: {e}")

    print(f"\nГотово. Обновлено строк: {updated}")


if __name__ == "__main__":
    run()

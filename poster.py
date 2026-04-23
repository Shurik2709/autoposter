# Social Autoposter
import os
import json
import time
import requests
from datetime import datetime
import pytz
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = "Posts"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

VK_TOKEN = os.environ.get("VK_TOKEN", "")
VK_GROUP_ID = os.environ.get("VK_GROUP_ID", "")

ZEN_CHANNEL_ID = os.environ.get("ZEN_CHANNEL_ID", "")

COL = {
    "post_id": 1,
    "text": 2,
    "image_url": 3,
    "publish_time": 4,
    "telegram": 5,
    "vk": 6,
    "zen": 7,
    "status": 8,
    "error_message": 9,
}


def get_sheet():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS не задан")
    creds_data = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet(SHEET_NAME)


def post_to_telegram(text, image_url):
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    if image_url:
        resp = requests.post(
            f"{base}/sendPhoto",
            data={"chat_id": TELEGRAM_CHANNEL_ID, "photo": image_url, "caption": text, "parse_mode": "HTML"},
            timeout=30,
        )
    else:
        resp = requests.post(
            f"{base}/sendMessage",
            data={"chat_id": TELEGRAM_CHANNEL_ID, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data.get('description', data)}")


def _vk_upload_photo(image_url):
    resp = requests.get(
        "https://api.vk.com/method/photos.getWallUploadServer",
        params={"group_id": VK_GROUP_ID, "access_token": VK_TOKEN, "v": "5.199"},
        timeout=30,
    ).json()
    upload_url = resp["response"]["upload_url"]
    img_data = requests.get(image_url, timeout=30).content
    upload_resp = requests.post(
        upload_url,
        files={"photo": ("image.jpg", img_data, "image/jpeg")},
        timeout=60,
    ).json()
    save_resp = requests.get(
        "https://api.vk.com/method/photos.saveWallPhoto",
        params={
            "group_id": VK_GROUP_ID,
            "photo": upload_resp["photo"],
            "server": upload_resp["server"],
            "hash": upload_resp["hash"],
            "access_token": VK_TOKEN,
            "v": "5.199",
        },
        timeout=30,
    ).json()
    photo = save_resp["response"][0]
    return f"photo{photo['owner_id']}_{photo['id']}"


def post_to_vk(text, image_url):
    attachments = ""
    if image_url:
        attachments = _vk_upload_photo(image_url)
    resp = requests.get(
        "https://api.vk.com/method/wall.post",
        params={
            "owner_id": f"-{VK_GROUP_ID}",
            "from_group": 1,
            "message": text,
            "attachments": attachments,
            "access_token": VK_TOKEN,
            "v": "5.199",
        },
        timeout=30,
    ).json()
    if "error" in resp:
        raise RuntimeError(f"VK error: {resp['error'].get('error_msg', resp['error'])}")


def post_to_zen(text, image_url, post_id):
    rss_file = "zen_feed.xml"
    if os.path.exists(rss_file):
        with open(rss_file, encoding="utf-8") as f:
            content = f.read()
        insert_pos = content.find("</channel>")
    else:
        content = '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">\n  <channel>\n    <title>My Channel</title>\n    <link>https://example.com</link>\n    <description>Auto-generated feed</description>\n</channel>\n</rss>'
        insert_pos = content.find("</channel>")
    now = datetime.now(MOSCOW_TZ).strftime("%a, %d %b %Y %H:%M:%S %z")
    image_tag = f'<media:content url="{image_url}" medium="image"/>' if image_url else ""
    new_item = f'\n    <item>\n      <title>{text[:80]}</title>\n      <description><![CDATA[{text}]]></description>\n      <pubDate>{now}</pubDate>\n      <guid>post-{post_id}</guid>\n      {image_tag}\n    </item>'
    new_content = content[:insert_pos] + new_item + "\n  " + content[insert_pos:]
    with open(rss_file, "w", encoding="utf-8") as f:
        f.write(new_content)


def run():
    sheet = get_sheet()
    rows = sheet.get_all_values()
    if len(rows) < 2:
        print("Нет постов в таблице.")
        return
    now_moscow = datetime.now(MOSCOW_TZ).replace(second=0, microsecond=0)
    data_rows = rows[1:]
    published_count = 0
    for i, row in enumerate(data_rows, start=2):
        row = row + [""] * (9 - len(row))
        post_id = row[0].strip()
        text = row[1].strip()
        image_url = row[2].strip()
        publish_time_str = row[3].strip()
        do_telegram = row[4].strip().upper() == "TRUE"
        do_vk = row[5].strip().upper() == "TRUE"
        do_zen = row[6].strip().upper() == "TRUE"
        status = row[7].strip().lower()
        if status != "pending":
            continue
        if not publish_time_str:
            continue
        try:
            publish_dt = datetime.strptime(publish_time_str, "%Y-%m-%d %H:%M")
            publish_dt = MOSCOW_TZ.localize(publish_dt)
        except ValueError:
            sheet.update_cell(i, COL["status"], "error")
            sheet.update_cell(i, COL["error_message"], f"Неверный формат времени: {publish_time_str}")
            continue
        if publish_dt > now_moscow:
            continue
        errors = []
        if do_telegram and TELEGRAM_BOT_TOKEN:
            try:
                post_to_telegram(text, image_url)
                print(f"[Строка {i}] OK Telegram")
                time.sleep(1)
            except Exception as e:
                errors.append(f"Telegram: {e}")
        if do_vk and VK_TOKEN:
            try:
                post_to_vk(text, image_url)
                print(f"[Строка {i}] OK VK")
                time.sleep(1)
            except Exception as e:
                errors.append(f"VK: {e}")
        if do_zen:
            try:
                post_to_zen(text, image_url, post_id)
                print(f"[Строка {i}] OK Zen")
            except Exception as e:
                errors.append(f"Zen: {e}")
        if errors:
            sheet.update_cell(i, COL["status"], "error")
            sheet.update_cell(i, COL["error_message"], "; ".join(errors))
        else:
            sheet.update_cell(i, COL["status"], "published")
            sheet.update_cell(i, COL["error_message"], "")
        published_count += 1
    print(f"Готово. Опубликовано: {published_count}")


if __name__ == "__main__":
    run()

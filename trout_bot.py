import os
import sqlite3
import requests
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# LINE Messaging API v3
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    FlexMessage,
    FlexContainer
)

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
USER_ID = os.environ.get('LINE_USER_ID', '').strip()
TARGET_URL = "https://troutisland.shop-pro.jp/"

DEFAULT_IMG = "https://raw.githubusercontent.com/line/line-images/master/blogs/20200806/logo.png"
DB_FILE = "data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS seen_items (
            url TEXT PRIMARY KEY,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_seen(key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT 1 FROM seen_items WHERE url = ?', (key,))
    row = c.fetchone()
    conn.close()
    return row is not None

def mark_as_seen(items):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for key, title in items:
        c.execute('INSERT OR IGNORE INTO seen_items (url, title) VALUES (?, ?)', (key, title))
    conn.commit()
    conn.close()

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def force_https(url_str):
    if not url_str:
        return ""
    if url_str.startswith("http://"):
        return "https://" + url_str[7:]
    return url_str

def create_flex_message(title, link, img_url):
    link = force_https(link)
    img_url = force_https(img_url) if img_url else DEFAULT_IMG

    # 長文によるFlex Message容量オーバー（30KB制限）を防ぐためタイトルを最大80文字にカット
    safe_title = title if len(title) <= 80 else title[:77] + "..."

    return {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": img_url,
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "【新入荷・在庫更新情報】",
                    "weight": "bold",
                    "color": "#1DB446",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": safe_title,
                    "weight": "bold",
                    "size": "md",
                    "wrap": True
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#1DB446",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "商品ページを開く",
                        "uri": link
                    }
                }
            ]
        }
    }

def extract_updates(soup):
    """新入荷・在庫更新情報枠から更新テキストと正確な個別商品/カテゴリURLを抽出"""
    items = []

    all_a_tags = soup.find_all('a', href=True)

    for a in all_a_tags:
        href = clean_text(a['href'])
        text = clean_text(a.get_text())

        if not href or href in ['/', '#'] or 'cart' in href or 'myaccount' in href:
            continue

        # 日付（M/D）を含むテキストリンクのみを精密抽出
        if re.search(r'\d{1,2}/\d{1,2}', text) and len(text) >= 5:
            full_url = force_https(urljoin(TARGET_URL, href))
            
            img_tag = a.find('img')
            if img_tag and img_tag.get('src'):
                img_url = force_https(urljoin(TARGET_URL, img_tag.get('src')))
            else:
                img_url = DEFAULT_IMG

            items.append((text, full_url, img_url))

    return items

def main():
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("エラー: Secretsが設定されていません。")
        return

    init_db()

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=10)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"サイトアクセスエラー: {e}")
        return

    raw_items = extract_updates(soup)
    
    new_items = []
    seen_keys = set()
    for title, url, img_url in raw_items:
        key = f"{title}_{url}"
        if key not in seen_keys:
            seen_keys.add(key)
            new_items.append((title, url, img_url, key))

    if not new_items:
        print("「新入荷＆在庫更新情報」の新しい更新はありませんでした。")
        return

    send_targets = new_items[:3]
    flex_messages = []

    for title, link, img_url, _ in send_targets:
        flex_json = create_flex_message(title, link, img_url)
        flex_container = FlexContainer.from_dict(flex_json)
        
        safe_alt = f"新着: {title}"[:40]
        flex_msg = FlexMessage(alt_text=safe_alt, contents=flex_container)
        flex_messages.append(flex_msg)

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            push_message_request = PushMessageRequest(
                to=USER_ID,
                messages=flex_messages
            )
            line_bot_api.push_message(push_message_request)
        
        mark_as_seen([(key, title) for title, _, _, key in send_targets])
        print(f"★容量制限を回避し、{len(send_targets)}件をLINEへ正常送信しました！")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

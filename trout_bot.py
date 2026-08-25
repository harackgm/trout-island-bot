import os
import sys
import sqlite3
import requests
import re
import hashlib
import urllib.parse
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# LINE Messaging API v3
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    BroadcastRequest,
    FlexMessage,
    FlexContainer
)

# ==========================================
# ★テスト送信専用設定（安全のため先頭1件のみ送信）
# ==========================================
TEST_MODE = True

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
TARGET_URL = "https://troutisland.shop-pro.jp/"
DB_FILE = "products.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS seen_items (
            item_key TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def generate_key(url, title):
    raw_str = f"{url}_{title}"
    return hashlib.md5(raw_str.encode('utf-8')).hexdigest()

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_updates(soup):
    items = []
    target_blocks = []
    
    for tag in soup.find_all(['td', 'div', 'p', 'table']):
        text = tag.get_text()
        if ('新入荷' in text or '在庫更新' in text or 'ご予約' in text or '予約' in text) and not ('オススメ' in text or 'おすすめ' in text):
            target_blocks.append(tag)

    if not target_blocks:
        target_blocks = [soup]

    for block in target_blocks:
        a_tags = block.find_all('a', href=True)
        for a in a_tags:
            href = clean_text(a['href'])
            text = clean_text(a.get_text())

            if not href or 'mode=cate' in href or 'cart' in href or 'myaccount' in href or href in ['/', '#']:
                continue

            parent_tag = a.parent
            parent_text = clean_text(parent_tag.get_text()) if parent_tag else ""
            display_title = text if len(text) >= 3 else parent_text

            if ('pid=' in href or 'shop-pro.jp' in href):
                full_url = urljoin(TARGET_URL, href)
                clean_title = re.sub(r'ご予約受付中！*|新入荷！*|再入荷！*|在庫更新！*', '', display_title).strip()
                if not clean_title:
                    clean_title = display_title
                if len(clean_title) > 2:
                    items.append((clean_title, full_url, None, "ご予約開始！"))
                    break

    return items

def create_flex_bubble(title, link, img_url, keyword):
    return {
        "type": "bubble",
        "size": "kilo", 
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {"type": "text", "text": keyword, "color": "#FF69B4", "size": "sm", "weight": "bold"},
                {"type": "text", "text": title, "wrap": True, "weight": "bold", "size": "sm", "maxLines": 3}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#00BFFF", "height": "sm", "action": {"type": "uri", "label": "詳細を見る", "uri": link or TARGET_URL}}
            ]
        }
    }

def main():
    if not CHANNEL_ACCESS_TOKEN:
        print("エラー: Secrets LINE_CHANNEL_ACCESS_TOKEN が設定されていません。")
        sys.exit(1)

    init_db()

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=10)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"アクセスエラー: {e}")
        return

    raw_items = extract_updates(soup)
    if not raw_items:
        print("テスト対象データが取得できませんでした。")
        return

    # ★安全対策：先頭1件のみ強制抽出（複数送信の事故を100%防止）
    title, url, img_url, keyword = raw_items[0]
    print(f"★テスト送信実行中（1件のみ抽出）: {title}")

    bubble = create_flex_bubble(title, url, img_url, keyword)
    flex_container_dict = {"type": "carousel", "contents": [bubble]}
    flex_message = FlexMessage(alt_text="【テスト送信】(1件)", contents=FlexContainer.from_dict(flex_container_dict))

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            broadcast_request = BroadcastRequest(messages=[flex_message])
            line_bot_api.broadcast(broadcast_request)
        
        print("★テスト送信成功！LINEへ1通届いているか確認してください。")

    except Exception as e:
        err_msg = str(e)
        print(f"★送信失敗: {err_msg}")
        if "monthly limit" in err_msg.lower() or "429" in err_msg:
            print("【緊急警告】LINEの月間送信上限に達しました！")
            sys.exit(1)

if __name__ == "__main__":
    main()

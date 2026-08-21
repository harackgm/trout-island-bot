import os
import sqlite3
import requests
import re
import hashlib
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

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
TARGET_URL = "https://troutisland.shop-pro.jp/"
DB_FILE = "products.db"

def init_db():
    """DBを初期化し、テーブルが空（初回起動）かどうかを判定する"""
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
    
    c.execute('SELECT COUNT(*) FROM seen_items')
    count = c.fetchone()[0]
    conn.close()
    return count == 0

def generate_key(date_str, title, url):
    """日付・タイトル・URLの3つを組み合わせて唯一無二の識別キーを作成"""
    raw_str = f"{date_str}_{title}_{url}"
    return hashlib.md5(raw_str.encode('utf-8')).hexdigest()

def is_seen(item_key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT 1 FROM seen_items WHERE item_key = ?', (item_key,))
    row = c.fetchone()
    conn.close()
    return row is not None

def mark_as_seen(items):
    """取得したアイテムをDBに登録して既読化"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for item_key, url, title in items:
        c.execute('INSERT OR IGNORE INTO seen_items (item_key, url, title) VALUES (?, ?, ?)', (item_key, url, title))
    conn.commit()
    conn.close()

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_updates(soup):
    """HPから日付、タイトル、リンクを正確に一組として抽出"""
    items = []
    
    target_blocks = []
    for tag in soup.find_all(['td', 'div', 'p', 'table']):
        text = tag.get_text()
        if ('新入荷' in text or '在庫更新' in text or '再入荷' in text or '新色' in text or '更新！' in text) and not ('オススメ' in text or 'おすすめ' in text):
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

            parent_text = clean_text(a.parent.get_text()) if a.parent else ""
            
            # 日付（例: 8/20, 08/20）を探す
            date_match = re.search(r'(\d{1,2}/\d{1,2})', text) or re.search(r'(\d{1,2}/\d{1,2})', parent_text)
            date_str = date_match.group(1) if date_match else "NODATE"

            if (date_match or '更新' in text or '入荷' in text) and ('pid=' in href or 'shop-pro.jp' in href or 'mode=' in href):
                full_url = urljoin(TARGET_URL, href)
                items.append((date_str, text, full_url))

    return items

def create_carousel_flex(new_items):
    """新着商品をカルーセル形式（横スクロールカード）のFlex Message JSONに変換"""
    bubbles = []
    
    for item_key, date_str, title, link in new_items:
        display_title = f"[{date_str}] {title}" if date_str != "NODATE" else title
        bubble = {
            "type": "bubble",
            "size": "micro",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "新着・再入荷情報",
                        "weight": "bold",
                        "color": "#1DB446",
                        "size": "xs"
                    },
                    {
                        "type": "text",
                        "text": display_title,
                        "weight": "bold",
                        "size": "sm",
                        "wrap": True,
                        "margin": "md",
                        "maxLines": 3
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "商品を見る",
                            "uri": link
                        },
                        "style": "primary",
                        "color": "#00B900",
                        "size": "sm"
                    }
                ]
            }
        }
        bubbles.append(bubble)

    flex_payload = {
        "type": "carousel",
        "contents": bubbles
    }
    return flex_payload

def main():
    if not CHANNEL_ACCESS_TOKEN:
        print("エラー: Secrets LINE_CHANNEL_ACCESS_TOKEN が設定されていません。")
        return

    is_first_run = init_db()

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=10)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"サイトアクセスエラー: {e}")
        return

    raw_items = extract_updates(soup)
    
    all_current_items = []
    for date_str, title, url in raw_items:
        item_key = generate_key(date_str, title, url)
        all_current_items.append((item_key, url, f"[{date_str}] {title}"))

    if is_first_run:
        mark_as_seen(all_current_items)
        print(f"★初回セットアップ完了: 過去データ {len(all_current_items)}件をすべてDB登録しました（通知は送信されません）。")
        return

    new_items = []
    seen_keys = set()
    
    for date_str, title, url in raw_items:
        item_key = generate_key(date_str, title, url)
        if item_key not in seen_keys and not is_seen(item_key):
            seen_keys.add(item_key)
            new_items.append((item_key, date_str, title, url))

    if not new_items:
        print("「新入荷＆在庫更新情報」の新しい更新はありませんでした。")
        return

    # 今回の全アイテムをDB登録
    mark_as_seen(all_current_items)

    send_targets = new_items[:10]

    flex_json = create_carousel_flex(send_targets)
    flex_container = FlexContainer.from_dict(flex_json)
    
    flex_message = FlexMessage(
        alt_text=f"【入荷・更新情報】({len(send_targets)}件)",
        contents=flex_container
    )

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            broadcast_request = BroadcastRequest(messages=[flex_message])
            line_bot_api.broadcast(broadcast_request)
        
        print(f"★全登録者へカルーセル新着・在庫更新 {len(send_targets)}件を正常送信しました。")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

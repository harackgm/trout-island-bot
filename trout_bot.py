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
    TextMessage
)

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
    
    c.execute('SELECT COUNT(*) FROM seen_items')
    count = c.fetchone()[0]
    conn.close()
    return count == 0

def generate_key(url, title):
    raw_str = f"{url}_{title}"
    return hashlib.md5(raw_str.encode('utf-8')).hexdigest()

def is_seen(item_key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT 1 FROM seen_items WHERE item_key = ?', (item_key,))
    row = c.fetchone()
    conn.close()
    return row is not None

def mark_as_seen(items):
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
    items = []
    
    target_blocks = []
    for tag in soup.find_all(['td', 'div', 'p', 'table']):
        text = tag.get_text()
        if ('新入荷' in text or '在庫更新' in text) and not ('オススメ' in text or 'おすすめ' in text):
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
            has_date = bool(re.search(r'\d{1,2}/\d{1,2}', text) or re.search(r'\d{1,2}/\d{1,2}', parent_text))

            if has_date and ('pid=' in href or 'shop-pro.jp' in href):
                full_url = urljoin(TARGET_URL, href)
                items.append((text, full_url))

    return items

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
    
    if is_first_run:
        all_to_mark = []
        for title, url in raw_items:
            item_key = generate_key(url, title)
            all_to_mark.append((item_key, url, title))
        
        mark_as_seen(all_to_mark)
        print(f"★初回セットアップ完了: 過去のデータ {len(all_to_mark)}件をDBに登録しました。")
        return

    new_items = []
    seen_keys = set()
    
    for title, url in raw_items:
        item_key = generate_key(url, title)
        if item_key not in seen_keys and not is_seen(item_key):
            seen_keys.add(item_key)
            new_items.append((item_key, title, url))

    if not new_items:
        print("「新入荷＆在庫更新情報」の新しい更新はありませんでした。")
        return

    # 1度の更新通知で送る商品を最大5件に設定
    send_targets = new_items[:5]
    messages = []

    # 全体ヘッダー
    messages.append(TextMessage(text=f"【新着・在庫更新情報】({len(send_targets)}件)"))

    # 各商品のテキスト＋URL
    for item_key, title, link in send_targets:
        msg_text = f"■ {title}\n{link}"
        messages.append(TextMessage(text=msg_text))

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            
            # LINE APIの上限（1リクエスト最大5件）に合わせて分割して送信
            chunk_size = 5
            for i in range(0, len(messages), chunk_size):
                chunk = messages[i:i + chunk_size]
                broadcast_request = BroadcastRequest(messages=chunk)
                line_bot_api.broadcast(broadcast_request)
        
        mark_as_seen([(item_key, url, title) for item_key, title, url in send_targets])
        print(f"★全登録者へ新着・在庫更新 {len(send_targets)}件を正常送信しました。")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

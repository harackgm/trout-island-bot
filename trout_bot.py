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

    # 初回起動（DBにデータが一切ない状態）かどうか判定
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
    
    # サイト上の全アイテム情報を整理
    all_current_items = []
    for title, url in raw_items:
        item_key = generate_key(url, title)
        all_current_items.append((item_key, url, title))

    # 【初回起動時】通知せず、すべてDB登録（初回セットアップ）して終了
    if is_first_run:
        mark_as_seen(all_current_items)
        print(f"★初回セットアップ完了: 過去データ {len(all_current_items)}件をすべてDB登録しました（通知は送信されません）。")
        return

    # 【通常実行時】未登録の新着差分のみをチェック
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

    # 送信前に今回検知されたデータを全件DB登録
    mark_as_seen(all_current_items)

    # 1回の送信上限（最大5件）
    send_targets = new_items[:5]
    messages = []

    messages.append(TextMessage(text=f"【新着・在庫更新情報】({len(send_targets)}件)"))

    for item_key, title, link in send_targets:
        msg_text = f"■ {title}\n{link}"
        messages.append(TextMessage(text=msg_text))

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            
            chunk_size = 5
            for i in range(0, len(messages), chunk_size):
                chunk = messages[i:i + chunk_size]
                broadcast_request = BroadcastRequest(messages=chunk)
                line_bot_api.broadcast(broadcast_request)
        
        print(f"★全登録者へ新着・在庫更新 {len(send_targets)}件を正常送信しました。")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

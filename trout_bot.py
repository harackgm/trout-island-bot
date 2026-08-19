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
    TextMessage
)

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
USER_ID = os.environ.get('LINE_USER_ID', '').strip()
TARGET_URL = "https://troutisland.shop-pro.jp/"
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

def extract_updates(soup):
    """「新入荷・在庫更新情報」枠内の日付付き商品リンクのみをピンポイント抽出"""
    items = []
    
    # ページ全体から「新入荷」等の見出しを持つ親要素を探す
    news_area = None
    for element in soup.find_all(['div', 'td', 'table', 'section']):
        text = element.get_text()
        if '新入荷' in text and '在庫更新' in text:
            # 最も深くネストされた更新枠を優先特定
            news_area = element
            break

    search_target = news_area if news_area else soup

    # 日付(例: 3/26)が含まれるテキストノードとリンク(aタグ)の関係を解析
    a_tags = search_target.find_all('a', href=True)
    for a in a_tags:
        href = clean_text(a['href'])
        text = clean_text(a.get_text())

        # 不要なナビゲーションやカテゴリリンク(mode=cate)を徹底除外
        if not href or 'mode=cate' in href or 'cart' in href or 'myaccount' in href or href == '/':
            continue

        # 商品個別ページ(pid=) または 日付が含まれるリンクのみ対象
        parent_text = a.parent.get_text() if a.parent else ""
        has_date = bool(re.search(r'\d{1,2}/\d{1,2}', text) or re.search(r'\d{1,2}/\d{1,2}', parent_text))

        if 'pid=' in href or (has_date and len(text) >= 3):
            full_url = force_https(urljoin(TARGET_URL, href))
            items.append((text, full_url))

    return items

def main():
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("エラー: Secretsが設定されていません。")
        return

    init_db()

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
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
    for title, url in raw_items:
        key = f"{title}_{url}"
        if key not in seen_keys and not is_seen(key):
            seen_keys.add(key)
            new_items.append((title, url, key))

    if not new_items:
        print("「新入荷＆在庫更新情報」の新しい更新はありませんでした。")
        return

    # 最新の最大3件を対象
    send_targets = new_items[:3]
    text_messages = []

    for title, link, _ in send_targets:
        # 正しい商品リンクとタイトルのみを組み立てて送信
        msg_text = f"【新着・在庫更新】\n{title}\n\n{link}"
        text_messages.append(TextMessage(text=msg_text))

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            push_message_request = PushMessageRequest(
                to=USER_ID,
                messages=text_messages
            )
            line_bot_api.push_message(push_message_request)
        
        mark_as_seen([(key, title) for title, _, key in send_targets])
        print(f"★新入荷枠のみを正しく検出し、{len(send_targets)}件送信しました！")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

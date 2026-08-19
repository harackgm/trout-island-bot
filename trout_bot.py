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

def is_seen(url):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT 1 FROM seen_items WHERE url = ?', (url,))
    row = c.fetchone()
    conn.close()
    return row is not None

def mark_as_seen(items):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for url, title in items:
        c.execute('INSERT OR IGNORE INTO seen_items (url, title) VALUES (?, ?)', (url, title))
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
    img_url = force_https(img_url)

    if not img_url or not img_url.startswith("https://"):
        img_url = "https://img07.shop-pro.jp/PA01271/083/etc/logo.png"

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
                    "text": "【新入荷・在庫更新】",
                    "weight": "bold",
                    "color": "#1DB446",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": title,
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

def extract_new_arrivals(soup):
    """新入荷＆在庫更新情報ブロックからリンクを抽出"""
    items = []
    
    # 「新入荷＆在庫更新情報」の文字を探す
    header_node = soup.find(lambda tag: tag.name in ['td', 'th', 'div', 'b', 'font', 'p'] and '新入荷＆在庫更新情報' in tag.text)
    
    if not header_node:
        return items

    # 親要素を遡って更新情報が含まれるコンテナ要素を取得
    container = header_node.find_parent(['table', 'div', 'td'])
    if not container:
        container = soup

    # エリア内のリンクを巡回
    for a in container.find_all('a', href=True):
        href = clean_text(a['href'])
        
        # 不要なリンクをスキップ
        if not href or href in ['/', '#', 'javascript:void(0);'] or 'cart' in href or 'myaccount' in href:
            continue
        
        # 親要素や周辺テキストも含めてタイトルを取得
        parent_text = clean_text(a.parent.get_text()) if a.parent else ""
        text = clean_text(a.get_text())
        
        # リンクテキストが短すぎる場合（「詳細」など）、親要素のテキストを採用
        full_title = parent_text if len(parent_text) > len(text) and len(parent_text) < 120 else text
        
        if not full_title or len(full_title) < 3:
            continue
            
        full_url = force_https(urljoin(TARGET_URL, href))
        
        # 画像取得
        img_tag = a.find('img')
        if img_tag and img_tag.get('src'):
            img_url = force_https(urljoin(TARGET_URL, img_tag.get('src')))
        else:
            img_url = "https://img07.shop-pro.jp/PA01271/083/etc/logo.png"

        items.append((full_title, full_url, img_url))

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

    raw_items = extract_new_arrivals(soup)
    
    # 未読アイテムのみ抽出（重複除去）
    new_items = []
    seen_urls = set()
    for title, url, img_url in raw_items:
        if url not in seen_urls and not is_seen(url):
            seen_urls.add(url)
            new_items.append((title, url, img_url))

    if not new_items:
        print("「新入荷＆在庫更新情報」の新しい更新はありませんでした。")
        return

    # 初回または大量検出時は最新最大5件に制限して通知
    send_targets = new_items[:5]
    flex_messages = []

    for title, link, img_url in send_targets:
        flex_json = create_flex_message(title, link, img_url)
        flex_container = FlexContainer.from_dict(flex_json)
        flex_msg = FlexMessage(alt_text=f"新入荷: {title}", contents=flex_container)
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
        
        mark_as_seen([(url, title) for title, url, _ in send_targets])
        print(f"★「新入荷＆在庫更新情報」から{len(send_targets)}件をLINEへ通知しました。")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

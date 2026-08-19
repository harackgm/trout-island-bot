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
                    "text": "【新入荷・在庫更新情報】",
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
    """「新入荷＆在庫更新情報」の枠内から更新行を正確に解析して取得"""
    items = []
    
    # 「新入荷＆在庫更新情報」を含む要素を探す
    target_node = soup.find(lambda tag: '新入荷＆在庫更新情報' in tag.text if tag.text else False)
    if not target_node:
        return items

    # 親のテーブル枠を取得
    parent_box = target_node.find_parent(['td', 'table', 'div'])
    if not parent_box:
        parent_box = soup

    # 枠内のテキストを行ごとに分離（日付「M/D」が含まれる行を探す）
    lines = parent_box.get_text().split('\n')
    
    # 枠内のリンク一覧（フォールバック用）
    links_in_box = parent_box.find_all('a', href=True)
    
    for line in lines:
        cleaned_line = clean_text(line)
        # 「8/19」等の日付パターンが含まれている行をターゲットにする
        if re.search(r'\d{1,2}/\d{1,2}', cleaned_line) and len(cleaned_line) > 5:
            # 該当行に関連するリンクを探す
            item_url = TARGET_URL
            img_url = "https://img07.shop-pro.jp/PA01271/083/etc/logo.png"

            for a in links_in_box:
                a_text = clean_text(a.get_text())
                # リンクテキストが更新行のキーワードと一部一致する場合、そのURLを採用
                if a_text and (a_text in cleaned_line or any(w in a_text for w in cleaned_line.split() if len(w) > 2)):
                    href = a['href']
                    if href not in ['/', '#'] and 'cart' not in href:
                        item_url = force_https(urljoin(TARGET_URL, href))
                        img_tag = a.find('img')
                        if img_tag and img_tag.get('src'):
                            img_url = force_https(urljoin(TARGET_URL, img_tag.get('src')))
                        break

            # 重複防止識別キーとしてタイトルとURLを使用
            items.append((cleaned_line, item_url, img_url))

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
    
    new_items = []
    seen_urls = set()
    for title, url, img_url in raw_items:
        # タイトル+URLをユニークキーとしてチェック
        unique_key = f"{url}#{title}"
        if unique_key not in seen_urls and not is_seen(unique_key):
            seen_urls.add(unique_key)
            new_items.append((title, url, img_url, unique_key))

    if not new_items:
        print("「新入荷＆在庫更新情報」の新しい更新はありませんでした。")
        return

    # 最新の最大5件をLINEへ送信
    send_targets = new_items[:5]
    flex_messages = []

    for title, link, img_url, _ in send_targets:
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
        
        # 通知したアイテムを記録
        mark_as_seen([(key, title) for title, _, _, key in send_targets])
        print(f"★「新入荷＆在庫更新情報」から{len(send_targets)}件をLINEへ通知しました。")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

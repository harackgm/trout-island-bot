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
DEFAULT_IMG = "https://img07.shop-pro.jp/PA01271/083/etc/logo.png"
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

def extract_updates(soup):
    """HTML全体のテキスト行から日付入りの新着行と、そのリンク・画像を抽出"""
    items = []

    # ページ内のすべてのリンクタグを取得
    all_links = soup.find_all('a', href=True)

    # ページ全体のテキストを行単位に分割
    raw_text = soup.get_text()
    lines = [clean_text(l) for l in raw_text.split('\n') if clean_text(l)]

    for line in lines:
        # 「8/19」や「08/19」などの日付が含まれる行を特定
        if re.search(r'\d{1,2}/\d{1,2}', line) and len(line) > 5:
            matched_url = TARGET_URL
            matched_img = DEFAULT_IMG

            # 行の文字列に該当するリンクを探す
            for a in all_links:
                href = a['href']
                a_text = clean_text(a.get_text())

                if not href or href in ['/', '#'] or 'cart' in href or 'myaccount' in href:
                    continue

                # リンクテキストが行内に含まれている、またはURLがカテゴリ/商品を示している場合
                if (a_text and a_text in line) or ('mode=' in href or 'pid=' in href):
                    # 行内の単語と一部一致するか検証
                    words = [w for w in line.split() if len(w) > 1]
                    if any(w in a_text for w in words):
                        matched_url = force_https(urljoin(TARGET_URL, href))
                        img_tag = a.find('img')
                        if img_tag and img_tag.get('src'):
                            matched_img = force_https(urljoin(TARGET_URL, img_tag.get('src')))
                        break

            items.append((line, matched_url, matched_img))

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
    
    # 最新の3件を抽出
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

    # テストとして最新最大3件を送信
    send_targets = new_items[:3]
    flex_messages = []

    for title, link, img_url, _ in send_targets:
        flex_json = create_flex_message(title, link, img_url)
        flex_container = FlexContainer.from_dict(flex_json)
        flex_msg = FlexMessage(alt_text=f"新着: {title}", contents=flex_container)
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
        print(f"★新着更新情報を{len(send_targets)}件、LINEへ送信しました！")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

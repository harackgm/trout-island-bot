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

# デフォルト画像（画像ホスティング失敗時）
DEFAULT_IMG = "https://raw.githubusercontent.com/line/line-images/master/blogs/20200806/logo.png"

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
    
    # DBが空（初回実行）かどうかチェック
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

def upload_to_imgur(image_bytes):
    """取得した画像データをImgurに匿名アップロードしてLINEで確実に表示可能なURLを生成"""
    try:
        headers = {"Authorization": "Client-ID 1c3eb7d8adfa2e3"}
        response = requests.post(
            "https://api.imgur.com/3/image",
            headers=headers,
            data={"image": image_bytes},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return data["data"]["link"]
    except Exception as e:
        print(f"Imgurアップロード失敗: {e}")
    return DEFAULT_IMG

def fetch_product_image(product_url, headers):
    try:
        res = requests.get(product_url, headers=headers, timeout=5)
        res.encoding = res.apparent_encoding
        p_soup = BeautifulSoup(res.text, "html.parser")
        
        img_src = None
        # OGP画像の取得
        og_img = p_soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            img_src = og_img.get("content")
        else:
            # 商品本体画像の取得
            img_tag = p_soup.find("img", id="product_image") or p_soup.find("img", class_="product_image")
            if img_tag and img_tag.get("src"):
                img_src = img_tag.get("src")
        
        if img_src:
            if img_src.startswith("//"):
                img_src = "https:" + img_src
            elif img_src.startswith("http://"):
                img_src = img_src.replace("http://", "https://", 1)
            elif not img_src.startswith("http"):
                img_src = urljoin(product_url, img_src)
            
            clean_url = img_src.split('?')[0]
            
            # 画像本体を一度ダウンロード（GitHub Actions経由ならブロックされない）
            img_res = requests.get(clean_url, headers=headers, timeout=5)
            if img_res.status_code == 200:
                # 確実に表示できる外部ホスティングへ転送
                return upload_to_imgur(img_res.content)
            
    except Exception as e:
        print(f"画像取得スキップ ({product_url}): {e}")
    
    return DEFAULT_IMG

def create_bubble(title, link, img_url):
    safe_title = title if len(title) <= 60 else title[:57] + "..."
    
    return {
        "type": "bubble",
        "size": "micro",
        "hero": {
            "type": "image",
            "url": img_url,
            "size": "full",
            "aspectRatio": "4:3",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "【新着・更新】",
                    "weight": "bold",
                    "color": "#1DB446",
                    "size": "xs"
                },
                {
                    "type": "text",
                    "text": safe_title,
                    "weight": "bold",
                    "size": "xs",
                    "wrap": True,
                    "margin": "xs"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#1DB446",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "詳細",
                        "uri": link
                    }
                }
            ]
        }
    }

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

    # DB初期化 & 初回起動（DBが空）かどうかチェック
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
    
    # 初回実行時：全アイテムをDBに登録して通知はスキップする
    if is_first_run:
        all_to_mark = []
        for title, url in raw_items:
            item_key = generate_key(url, title)
            all_to_mark.append((item_key, url, title))
        
        mark_as_seen(all_to_mark)
        print(f"★初回セットアップ完了: 過去のデータ {len(all_to_mark)}件をDBに登録しました。（LINE通知はスキップしました）")
        return

    # 2回目以降：未通知の差分だけを抽出
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

    send_targets = new_items[:7]
    bubbles = []

    for item_key, title, link in send_targets:
        img_url = fetch_product_image(link, headers)
        bubble_json = create_bubble(title, link, img_url)
        bubbles.append(bubble_json)

    carousel_json = {
        "type": "carousel",
        "contents": bubbles
    }

    flex_container = FlexContainer.from_dict(carousel_json)
    flex_msg = FlexMessage(alt_text=f"新着・在庫更新情報 ({len(send_targets)}件)", contents=flex_container)

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            broadcast_request = BroadcastRequest(messages=[flex_msg])
            line_bot_api.broadcast(broadcast_request)
        
        mark_as_seen([(item_key, url, title) for item_key, title, url in send_targets])
        print(f"★全登録者へ新着・在庫更新 {len(send_targets)}件のカルーセル通知を一括送信しました。")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

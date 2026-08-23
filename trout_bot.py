import os
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
# ★テストモード設定（True: 強制5件通知 / False: 通常動作）
# イレギュラーパターンの抽出テスト用
# ==========================================
TEST_MODE = True
MAX_NOTIFY_LIMIT = 5

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
        extracted_texts = set()
        
        # 1. 通常のリンクあり商品の抽出
        for a in a_tags:
            href = clean_text(a['href'])
            text = clean_text(a.get_text())

            if not href or 'mode=cate' in href or 'cart' in href or 'myaccount' in href or href in ['/', '#']:
                continue

            parent_text = clean_text(a.parent.get_text()) if a.parent else ""
            has_date = bool(re.search(r'\d{1,2}/\d{1,2}', text) or re.search(r'\d{1,2}/\d{1,2}', parent_text))

            if has_date and ('pid=' in href or 'shop-pro.jp' in href):
                full_url = urljoin(TARGET_URL, href)
                
                status_keyword = "更新・お知らせ"
                full_check_text = text + " " + parent_text
                if "新入荷" in full_check_text:
                    status_keyword = "新入荷！"
                elif "再入荷" in full_check_text:
                    status_keyword = "再入荷！"
                elif "予約" in full_check_text:
                    status_keyword = "ご予約開始！"

                extracted_texts.add(text)
                items.append((text, full_url, status_keyword))

        # 2. リンクなし（イレギュラー告知）の抽出
        lines = block.get_text(separator='\n').split('\n')
        for i, line in enumerate(lines):
            clean_line = clean_text(line)
            if not clean_line:
                continue
            
            # ★「特価コーナー」「店頭販売中」「ネット販売」を含む行を検知
            if "店頭販売中" in clean_line or "ネット販売" in clean_line or "特価コーナー" in clean_line:
                # 既にリンクありとして抽出済みの場合はスキップ
                if any(ext_text in clean_line for ext_text in extracted_texts):
                    continue
                
                title = clean_line
                # 「↑」記号があれば、前の行と結合して1つの商品名にする
                if "↑" in clean_line and i > 0:
                    title = clean_text(lines[i-1]) + " " + clean_line

                link = "" 
                status_keyword = "お知らせ"
                
                # キーワード判定
                if "特価コーナー" in title:
                    status_keyword = "特価コーナー！"
                elif "ネット販売" in title:
                    status_keyword = "予告・お知らせ"
                elif "店頭販売中" in title:
                    status_keyword = "店頭販売中！"

                items.append((title, link, status_keyword))

    # 重複の排除
    unique_items = []
    seen_titles = set()
    for item in items:
        if item[0] not in seen_titles:
            unique_items.append(item)
            seen_titles.add(item[0])

    return unique_items

def fetch_product_image(product_url):
    if not product_url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(product_url, headers=headers, timeout=5)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, "html.parser")
        
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            img_url = og_img["content"]
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            elif img_url.startswith("http://"):
                img_url = img_url.replace("http://", "https://")
            
            parsed = urllib.parse.urlparse(img_url)
            safe_path = urllib.parse.quote(parsed.path)
            img_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, safe_path, parsed.params, parsed.query, parsed.fragment))
            return img_url
    except Exception as e:
        print(f"画像取得エラー ({product_url}): {e}")
    return None

def create_flex_bubble(title, link, img_url, keyword):
    keyword_color = "#666666"
    if keyword == "新入荷！":
        keyword_color = "#FF4500"
    elif keyword == "再入荷！":
        keyword_color = "#32CD32"
    elif keyword == "特価コーナー！":
        keyword_color = "#FF0000" # 特価コーナーは赤色
    elif keyword in ["ご予約開始！", "店頭販売中！", "予告・お知らせ"]:
        keyword_color = "#FF69B4"

    bubble = {
        "type": "bubble",
        "size": "kilo", 
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": keyword,
                    "color": keyword_color,
                    "size": "sm",
                    "weight": "bold"
                },
                {
                    "type": "text",
                    "text": title,
                    "wrap": True,
                    "weight": "bold",
                    "size": "sm",
                    "maxLines": 3
                }
            ]
        }
    }

    if img_url:
        hero_section = {
            "type": "image",
            "url": img_url,
            "size": "full",
            "aspectRatio": "1:1",
            "aspectMode": "cover"
        }
        if link:
            hero_section["action"] = {
                "type": "uri",
                "uri": link
            }
        bubble["hero"] = hero_section

    if link:
        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#00BFFF",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "詳細を見る",
                        "uri": link
                    }
                }
            ],
            "flex": 0
        }

    return bubble

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
    all_current_items = [(generate_key(url, title), url, title) for title, url, keyword in raw_items]

    if is_first_run:
        mark_as_seen(all_current_items)
        print(f"★初回セットアップ完了: 過去データ {len(all_current_items)}件をDB登録しました。")
        if not TEST_MODE:
            return

    new_items = []
    seen_keys = set()

    if TEST_MODE:
        print("★テストモード実行中: DBチェックをスキップして最新アイテムを取得します。")
        for title, url, keyword in raw_items:
            item_key = generate_key(url, title)
            if item_key not in seen_keys:
                seen_keys.add(item_key)
                new_items.append((item_key, title, url, keyword))
    else:
        for title, url, keyword in raw_items:
            item_key = generate_key(url, title)
            if item_key not in seen_keys and not is_seen(item_key):
                seen_keys.add(item_key)
                new_items.append((item_key, title, url, keyword))

    if not new_items:
        print("「新入荷＆在庫更新情報」の新しい更新はありませんでした。")
        return

    if not TEST_MODE:
        mark_as_seen(all_current_items)

    send_targets = new_items[:MAX_NOTIFY_LIMIT]
    
    bubbles = []
    for item_key, title, link, keyword in send_targets:
        img_url = fetch_product_image(link) if link else None
        bubble = create_flex_bubble(title, link, img_url, keyword)
        bubbles.append(bubble)

    flex_container_dict = {
        "type": "carousel",
        "contents": bubbles
    }

    prefix_text = "【テスト送信】" if TEST_MODE else "【新着・在庫更新情報】"
    flex_message = FlexMessage(
        alt_text=f"{prefix_text}({len(send_targets)}件)",
        contents=FlexContainer.from_dict(flex_container_dict)
    )

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            broadcast_request = BroadcastRequest(messages=[flex_message])
            line_bot_api.broadcast(broadcast_request)
        
        print(f"★全登録者へ {len(send_targets)}件をFlex Message形式で正常送信しました。")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

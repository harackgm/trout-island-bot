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
# ★8/27検証テストモード（安全装置・通数保護）
# ==========================================
TEST_MODE = True
MAX_NOTIFY_LIMIT = 5

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
TARGET_URL = "https://troutisland.shop-pro.jp/"
SALE_URL = "http://troutisland.shop-pro.jp/?mode=cate&cbid=1923704&csid=0"
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

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_updates(soup):
    items = []
    
    # 1. 「新入荷＆在庫更新情報」のスクロール枠をピンポイント特定
    target_box = None
    for tag in soup.find_all(['td', 'div', 'p']):
        text = tag.get_text()
        if '新入荷＆在庫更新情報' in text:
            box = tag.find_next('div', style=lambda s: s and 'overflow' in s)
            if box:
                target_box = box
                break

    if not target_box:
        target_box = soup.find('div', style=lambda s: s and 'overflow-y: scroll' in s)

    if not target_box:
        print("更新情報枠が見つかりませんでした。")
        return []

    # 2. 枠内のHTMLを<br>タグで行ごとに分解（他行のキーワード混入を100%防止）
    box_html = str(target_box)
    raw_lines = re.split(r'<br\s*/?>', box_html, flags=re.IGNORECASE)

    for raw_line in raw_lines:
        line_soup = BeautifulSoup(raw_line, 'html.parser')
        line_text = clean_text(line_soup.get_text())
        
        if not line_text:
            continue

        a_tag = line_soup.find('a', href=True)
        if not a_tag:
            continue

        href = clean_text(a_tag['href'])
        if 'pid=' not in href:
            continue

        full_url = urljoin(TARGET_URL, href)
        link_text = clean_text(a_tag.get_text())

        # 日付(MM/DD)が含まれている行のみ抽出（日付のない「針子」等を完全排除）
        has_date = bool(re.search(r'\d{1,2}/\d{1,2}', line_text))
        is_reservation = ("予約" in line_text or "ご予約" in line_text)

        if not (has_date or is_reservation):
            continue

        # ★同じ行内のテキストだけから正確にステータスを判定
        if "ご予約" in line_text or "予約" in line_text:
            status_keyword = "ご予約開始！"
        elif "新色" in line_text:
            status_keyword = "新色追加！"
        elif "新入荷" in line_text:
            status_keyword = "新入荷！"
        elif "再入荷" in line_text or "在庫更新" in line_text:
            status_keyword = "再入荷！"
        else:
            status_keyword = "更新・お知らせ"

        clean_title = link_text
        if len(clean_title) < 3:
            temp_title = re.sub(r'\d{1,2}/\d{1,2}', '', line_text)
            temp_title = re.sub(r'ご予約受付中！*|新入荷！*|再入荷！*|在庫更新！*|新色追加！*|！', '', temp_title).strip()
            if len(temp_title) >= 3:
                clean_title = temp_title

        if len(clean_title) > 2:
            items.append((clean_title, full_url, None, status_keyword))

    unique_items = []
    seen_urls = set()
    for item in items:
        if item[1] not in seen_urls:
            unique_items.append(item)
            seen_urls.add(item[1])

    return unique_items

def fetch_product_image(product_url):
    if not product_url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(product_url, headers=headers, timeout=5)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, "html.parser")
        
        img_url = None
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if '/product/' in src and not 'icon' in src and not 'spacer' in src:
                img_url = src
                break
                
        if not img_url:
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                img_url = og_img["content"]

        if img_url:
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
    elif keyword == "新色追加！":
        keyword_color = "#9400D3"
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
        sys.exit(1)

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=10)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"アクセスエラー: {e}")
        return

    raw_items = extract_updates(soup)
    
    # 8/27の最新データを優先抽出
    target_items = [item for item in raw_items if "ココニョロ" in item[0] or "九重" in item[0]]
    if not target_items:
        target_items = raw_items[:2]

    send_targets = target_items[:MAX_NOTIFY_LIMIT]
    print(f"★抽出件数: {len(send_targets)}件")

    bubbles = []
    for title, link, pre_img_url, keyword in send_targets:
        img_url = fetch_product_image(link)
        bubble = create_flex_bubble(title, link, img_url, keyword)
        bubbles.append(bubble)

    flex_container_dict = {
        "type": "carousel",
        "contents": bubbles
    }

    flex_message = FlexMessage(
        alt_text=f"【8/27修正検証テスト】({len(send_targets)}件)",
        contents=FlexContainer.from_dict(flex_container_dict)
    )

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            broadcast_request = BroadcastRequest(messages=[flex_message])
            line_bot_api.broadcast(broadcast_request)
        
        print(f"★テスト送信完了: {len(send_targets)}件を正常送信しました。")

    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

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
# ★本番自動監視モード設定
# ==========================================
TEST_MODE = False
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
        if ('新入荷' in text or '在庫更新' in text or 'ご予約' in text or '予約' in text) and not ('オススメ' in text or 'おすすめ' in text):
            target_blocks.append(tag)

    if not target_blocks:
        target_blocks = [soup]

    for block in target_blocks:
        a_tags = block.find_all('a', href=True)
        extracted_texts = set()
        
        for a in a_tags:
            href = clean_text(a['href'])
            text = clean_text(a.get_text())

            # 商品詳細ページ(pid=を含む)以外のリンク（カテゴリー一覧・バナー等）を完全除外
            if not href or 'pid=' not in href:
                continue

            parent_tag = a.parent
            parent_text = clean_text(parent_tag.get_text()) if parent_tag else ""
            grandparent_text = clean_text(parent_tag.parent.get_text()) if parent_tag and parent_tag.parent else ""
            
            full_context_text = text + " " + parent_text + " " + grandparent_text
            
            display_title = text
            if len(display_title) < 3 and parent_text:
                display_title = parent_text

            has_date = bool(re.search(r'\d{1,2}/\d{1,2}', full_context_text))
            is_reservation = ("予約" in full_context_text or "ご予約" in full_context_text)

            if has_date or is_reservation:
                full_url = urljoin(TARGET_URL, href)
                
                status_keyword = "更新・お知らせ"
                if "予約" in full_context_text or "ご予約" in full_context_text:
                    status_keyword = "ご予約開始！"
                elif "新入荷" in full_context_text:
                    status_keyword = "新入荷！"
                elif "再入荷" in full_context_text:
                    status_keyword = "再入荷！"

                clean_title = re.sub(r'ご予約受付中！*|新入荷！*|再入荷！*|在庫更新！*', '', display_title).strip()
                if not clean_title:
                    clean_title = display_title

                if len(clean_title) > 2:
                    extracted_texts.add(clean_title)
                items.append((clean_title, full_url, None, status_keyword))

        lines = block.get_text(separator='\n').split('\n')
        for i, line in enumerate(lines):
            clean_line = clean_text(line)
            if not clean_line:
                continue
            
            if "店頭販売中" in clean_line or "ネット販売" in clean_line:
                if any(ext_text in clean_line for ext_text in extracted_texts):
                    continue
                
                title = clean_line
                if "↑" in clean_line and i > 0:
                    title = clean_text(lines[i-1]) + " " + clean_line

                link = "" 
                status_keyword = "お知らせ"
                if "ネット販売" in title:
                    status_keyword = "予告・お知らせ"
                elif "店頭販売中" in title:
                    status_keyword = "店頭販売中！"

                items.append((title, link, None, status_keyword))

    unique_items = []
    seen_titles = set()
    for item in items:
        if item[0] not in seen_titles:
            unique_items.append(item)
            seen_titles.add(item[0])

    return unique_items

def extract_sale_items():
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(SALE_URL, headers=headers, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, "html.parser")
        
        products = {}
        for a in soup.find_all('a', href=True):
            href = clean_text(a['href'])
            if 'pid=' in href:
                pid_match = re.search(r'pid=(\d+)', href)
                if pid_match:
                    pid = pid_match.group(1)
                    if pid not in products:
                        products[pid] = {"title": "", "img_url": None}
                    
                    text = clean_text(a.get_text())
                    if text and "SOLD OUT" not in text and not re.fullmatch(r'[\d,]+円.*', text):
                        if len(text) > len(products[pid]["title"]):
                            products[pid]["title"] = text
                        
                    img_tag = a.find('img')
                    if img_tag and img_tag.get('src'):
                        raw_src = img_tag.get('src')
                        if "spacer" not in raw_src and "icon" not in raw_src:
                            img_url = urljoin(SALE_URL, raw_src).replace("http://", "https://")
                            parsed = urllib.parse.urlparse(img_url)
                            safe_path = urllib.parse.quote(parsed.path)
                            products[pid]["img_url"] = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, safe_path, parsed.params, parsed.query, parsed.fragment))

        for pid, data in products.items():
            title = data["title"]
            img_url = data["img_url"]
            if title and img_url:
                items.append((title, SALE_URL, img_url, "特価コーナー！"))
            
    except Exception as e:
        print(f"特価コーナー取得エラー: {e}")
    return items

def fetch_product_image(product_url):
    """
    ショップの裏側設定(og:image)のミスに惑わされず、
    実際のページ上の本物画像を最優先で取得する2段階構造
    """
    if not product_url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(product_url, headers=headers, timeout=5)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, "html.parser")
        
        img_url = None
        
        # 1. ページ内の「/product/」画像URLを最優先取得
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if '/product/' in src and not 'icon' in src and not 'spacer' in src:
                img_url = src
                break
                
        # 2. 予備として og:image を使用
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
    elif keyword == "特価コーナー！":
        keyword_color = "#FF0000" 
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
    
    clean_site_text = clean_text(soup.get_text())
    if "特価" in clean_site_text:
        sale_items = extract_sale_items()
        raw_items = raw_items + sale_items 

    all_current_items = [(generate_key(url, title), url, title) for title, url, img_url, keyword in raw_items]

    if is_first_run:
        mark_as_seen(all_current_items)
        print(f"★初回セットアップ完了: 過去データ {len(all_current_items)}件をDB登録しました。")
        return

    new_items = []
    seen_keys = set()

    for title, url, img_url, keyword in raw_items:
        item_key = generate_key(url, title)
        if item_key not in seen_keys and not is_seen(item_key):
            seen_keys.add(item_key)
            new_items.append((item_key, title, url, img_url, keyword))

    if not new_items:
        print("「新入荷＆在庫更新情報」および「ご予約コーナー」の新しい更新はありませんでした。")
        return

    # ★大量通知ストッパー（安全装置）: 未読が5件を超える場合はLINE送信を行わず、全件DBのみ更新
    if len(new_items) > MAX_NOTIFY_LIMIT:
        print(f"★安全装置発動: 新着が{len(new_items)}件（上限{MAX_NOTIFY_LIMIT}件超え）のため、大量通知を防ぐべくDBのみ更新します。")
        mark_as_seen(all_current_items)
        return

    send_targets = new_items[:MAX_NOTIFY_LIMIT]
    
    bubbles = []
    for item_key, title, link, pre_img_url, keyword in send_targets:
        img_url = pre_img_url
        if not img_url and link:
            img_url = fetch_product_image(link)
            
        bubble = create_flex_bubble(title, link, img_url, keyword)
        bubbles.append(bubble)

    flex_container_dict = {
        "type": "carousel",
        "contents": bubbles
    }

    prefix_text = "【新着・在庫更新情報】"
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
        mark_as_seen(all_current_items)

    except Exception as e:
        err_msg = str(e)
        print(f"★送信エラーが発生しました: {err_msg}")
        
        if "monthly limit" in err_msg.lower() or "429" in err_msg:
            print("【緊急警告】LINEの月間送信上限（200通）に達しました！GitHub Actionsをエラー停止させて通知します。")
            sys.exit(1)
        else:
            print("一時的な通信エラーのため、未読データは次回へ繰り越します。")

if __name__ == "__main__":
    main()

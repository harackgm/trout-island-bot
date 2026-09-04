import os
import sys
import sqlite3
import requests
import re
import hashlib
import time
import urllib.parse
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup, Comment

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
# ★本番自動監視モード設定（カルーセル分割＆安全ストッパー作動）
# ==========================================
TEST_MODE = False
MAX_NOTIFY_LIMIT = 15       # 異常時ストッパー：16件以上の新着は送信スキップ
MAX_BUBBLES_PER_MSG = 5     # 1つの吹き出し(カルーセル)に入れる最大件数

# 日本時間(JST)の定義
JST = timezone(timedelta(hours=9))

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
            created_at TEXT
        )
    ''')
    conn.commit()
    c.execute('SELECT COUNT(*) FROM seen_items')
    count = c.fetchone()[0]
    conn.close()
    return count == 0

def generate_key(url, title, keyword, date_str):
    raw_str = f"{url}_{title}_{keyword}_{date_str}"
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
    now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
    for item_key, url, title in items:
        c.execute('INSERT OR IGNORE INTO seen_items (item_key, url, title, created_at) VALUES (?, ?, ?, ?)', 
                  (item_key, url, title, now_jst))
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
    target_boxes = []
    
    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    for c in comments:
        if "ここからご予約" in c or "ここから入荷情報" in c:
            box = c.find_next('div')
            if box and box not in target_boxes:
                target_boxes.append(box)

    if not target_boxes:
        target_boxes = soup.find_all('div', style=lambda s: s and 'overflow-y' in s)

    for target_box in target_boxes:
        box_html = str(target_box)
        raw_lines = re.split(r'<br\s*/?>', box_html, flags=re.IGNORECASE)

        for raw_line in raw_lines:
            line_soup = BeautifulSoup(raw_line, 'html.parser')
            
            a_tag = line_soup.find('a', href=True)
            if not a_tag:
                continue

            href = clean_text(a_tag['href'])
            if 'pid=' not in href:
                continue

            full_url = urljoin(TARGET_URL, href)
            link_text = clean_text(a_tag.get_text())
            line_full_text = clean_text(line_soup.get_text())

            date_match = re.search(r'\d{1,2}/\d{1,2}', line_full_text)
            date_str = date_match.group(0) if date_match else "no_date"

            if "ご予約" in line_full_text or "予約" in line_full_text:
                status_keyword = "ご予約開始！"
            elif "新色" in line_full_text:
                status_keyword = "新色追加！"
            elif "新入荷" in line_full_text:
                status_keyword = "新入荷！"
            elif "再入荷" in line_full_text or "在庫更新" in line_full_text:
                status_keyword = "再入荷！"
            else:
                status_keyword = "更新・お知らせ"

            clean_title = link_text
            if len(clean_title) < 3:
                temp_title = re.sub(r'\d{1,2}/\d{1,2}', '', line_full_text)
                temp_title = re.sub(r'ご予約受付中！*|新入荷！*|再入荷！*|在庫更新！*|新色追加！*|！', '', temp_title).strip()
                if len(temp_title) >= 3:
                    clean_title = temp_title

            if len(clean_title) > 2:
                items.append((clean_title, full_url, None, status_keyword, date_str))

    return items

def extract_recommend_items(soup):
    items = []
    product_items = soup.find_all('div', class_='product_item')
    
    for item_div in product_items:
        a_tag = item_div.find('a', href=True)
        if not a_tag:
            continue
            
        href = clean_text(a_tag['href'])
        if 'pid=' not in href:
            continue

        full_url = urljoin(TARGET_URL, href)
        
        name_div = item_div.find('div', class_='name')
        if name_div and name_div.find('a'):
            title = clean_text(name_div.find('a').get_text())
        else:
            title = clean_text(a_tag.get_text())

        if len(title) > 2:
            items.append((title, full_url, None, "おすすめ商品！", "no_date"))

    return items

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
                items.append((title, SALE_URL, img_url, "特価コーナー！", "no_date"))
            
    except Exception as e:
        print(f"特価コーナー取得エラー: {e}")
    return items

def fetch_product_details(product_url):
    if not product_url:
        return None, None
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

        price_text = None
        price_p = soup.find('p', class_='price_detail')
        if price_p:
            price_text = clean_text(price_p.get_text())
        else:
            og_price = soup.find("meta", property="product:price:amount")
            if og_price and og_price.get("content"):
                price_text = f"{og_price['content']}円"

        return img_url, price_text

    except Exception as e:
        print(f"詳細取得エラー ({product_url}): {e}")
    return None, None

def create_flex_bubble(title, link, img_url, keyword, price_text=None):
    keyword_color = "#666666"
    
    if "新入荷" in keyword:
        keyword_color = "#FF4500"
    elif "再入荷" in keyword:
        keyword_color = "#32CD32"
    elif "特価" in keyword or "おすすめ" in keyword:
        keyword_color = "#FF0000" 
    elif "新色" in keyword:
        keyword_color = "#9400D3"
    elif "予約" in keyword or "店頭" in keyword or "予告" in keyword:
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
                    "weight": "bold",
                    "wrap": True
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

    if price_text:
        bubble["body"]["contents"].append({
            "type": "text",
            "text": price_text,
            "color": "#e60012",
            "size": "sm",
            "weight": "bold",
            "margin": "sm"
        })

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

    raw_items = extract_updates(soup) + extract_recommend_items(soup)
    
    clean_site_text = clean_text(soup.get_text())
    if "特価" in clean_site_text:
        sale_items = extract_sale_items()
        raw_items = raw_items + sale_items 

    # サイト上の全カレントアイテムの個別のキー作成
    all_current_db_entries = []
    for title, url, img_url, keyword, date_str in raw_items:
        key = generate_key(url, title, keyword, date_str)
        all_current_db_entries.append((key, url, title))

    if is_first_run:
        mark_as_seen(all_current_db_entries)
        print(f"★初回セットアップ完了: 過去データ {len(all_current_db_entries)}件をDB登録しました。")
        return

    # ステップ1: 未読の「個別キー」だけを抽出
    unseen_items = []
    for title, url, img_url, keyword, date_str in raw_items:
        item_key = generate_key(url, title, keyword, date_str)
        if not is_seen(item_key):
            pid_match = re.search(r'pid=(\d+)', url)
            pid = pid_match.group(1) if pid_match else url
            unseen_items.append({
                'item_key': item_key,
                'pid': pid,
                'title': title,
                'url': url,
                'img_url': img_url,
                'keyword': keyword,
                'date_str': date_str
            })

    if not unseen_items:
        print("「新入荷＆在庫更新情報」「ご予約コーナー」「おすすめ商品」の新しい更新はありませんでした。")
        return

    # ステップ2: 今回の巡回で未読のアイテム同士をPID（商品ID）ごとに結合
    merged_unseen = {}
    for item in unseen_items:
        pid = item['pid']
        if pid in merged_unseen:
            if item['keyword'] not in merged_unseen[pid]['keywords']:
                merged_unseen[pid]['keywords'].append(item['keyword'])
            merged_unseen[pid]['keys'].append(item['item_key'])
        else:
            merged_unseen[pid] = {
                'title': item['title'],
                'url': item['url'],
                'img_url': item['img_url'],
                'keywords': [item['keyword']],
                'date_str': item['date_str'],
                'keys': [item['item_key']]
            }

    # 通知用リストと送信後にDB保存するキーのリストを作成
    new_items_to_notify = []
    all_keys_to_mark = []

    for pid, data in merged_unseen.items():
        combined_keyword = " ＆ ".join(data['keywords'])
        new_items_to_notify.append((data['title'], data['url'], data['img_url'], combined_keyword, data['date_str']))
        for k in data['keys']:
            all_keys_to_mark.append((k, data['url'], data['title']))

    # ステップ3: 大量通知ストッパーの判定
    if len(new_items_to_notify) > MAX_NOTIFY_LIMIT:
        print(f"★安全装置発動: 新着が{len(new_items_to_notify)}件（上限{MAX_NOTIFY_LIMIT}件超え）のため、大量通知を防ぐべくDBのみ最新基準で更新します。")
        mark_as_seen(all_current_db_entries)
        return

    # ステップ4: カルーセル作成と送信
    chunks = [new_items_to_notify[i:i + MAX_BUBBLES_PER_MSG] for i in range(0, len(new_items_to_notify), MAX_BUBBLES_PER_MSG)]
    flex_messages = []
    
    for i, chunk in enumerate(chunks):
        bubbles = []
        for title, link, pre_img_url, keyword, date_str in chunk:
            img_url = pre_img_url
            price_text = None
            
            if link:
                time.sleep(1) 
                fetched_img, fetched_price = fetch_product_details(link)
                if not img_url:
                    img_url = fetched_img
                price_text = fetched_price
                
            bubble = create_flex_bubble(title, link, img_url, keyword, price_text)
            bubbles.append(bubble)

        flex_container_dict = {
            "type": "carousel",
            "contents": bubbles
        }

        prefix_text = f"【新着・在庫更新情報】({i+1}/{len(chunks)})" if len(chunks) > 1 else "【新着・在庫更新情報】"
        flex_messages.append(FlexMessage(
            alt_text=f"{prefix_text} {len(chunk)}件",
            contents=FlexContainer.from_dict(flex_container_dict)
        ))

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            broadcast_request = BroadcastRequest(messages=flex_messages)
            line_bot_api.broadcast(broadcast_request)
        
        now_str = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{now_str} JST] ★全登録者へ 計{len(new_items_to_notify)}件（{len(flex_messages)}吹き出し）を正常送信しました。")
        
        # 送信に成功したため個別の全キーをDBに保存
        mark_as_seen(all_keys_to_mark)

    except Exception as e:
        err_msg = str(e)
        print(f"★送信エラーが発生しました: {err_msg}")
        
        if "monthly limit" in err_msg.lower() or "429" in err_msg or "quota" in err_msg.lower():
            print("[ERROR] 今月分のLINE通知上限（200通）に到達しました。")
            sys.exit(1)
        else:
            print("一時的な通信エラーのため、未読データは次回へ繰り越します。")

if __name__ == "__main__":
    main()

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
# ★8/25確認テスト用モード（安全制御・件数上限固定）
# ==========================================
TEST_MODE = True
MAX_NOTIFY_LIMIT = 5  # LINE API上限(12件)を確実に下回る安全枠

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
TARGET_URL = "https://troutisland.shop-pro.jp/"
DB_FILE = "products.db"

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
        for a in a_tags:
            href = clean_text(a['href'])
            text = clean_text(a.get_text())

            # 商品詳細ページ(pid=を含む)以外のリンクを除外
            if not href or 'pid=' not in href:
                continue

            parent_tag = a.parent
            parent_text = clean_text(parent_tag.get_text()) if parent_tag else ""
            grandparent_text = clean_text(parent_tag.parent.get_text()) if parent_tag and parent_tag.parent else ""
            
            full_context_text = text + " " + parent_text + " " + grandparent_text
            
            # 8/25の記載がある個別商品のみを抽出
            if "8/25" in full_context_text:
                full_url = urljoin(TARGET_URL, href)
                
                status_keyword = "更新・お知らせ"
                if "新入荷" in full_context_text:
                    status_keyword = "新入荷！"
                elif "在庫更新" in full_context_text or "再入荷" in full_context_text:
                    status_keyword = "再入荷！"

                clean_title = re.sub(r'ご予約受付中！*|新入荷！*|再入荷！*|在庫更新！*', '', text).strip()
                if not clean_title or len(clean_title) < 3:
                    clean_title = parent_text

                items.append((clean_title, full_url, None, status_keyword))

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
    keyword_color = "#FF4500" if keyword == "新入荷！" else "#32CD32"

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
        bubble["hero"] = {
            "type": "image",
            "url": img_url,
            "size": "full",
            "aspectRatio": "1:1",
            "aspectMode": "cover",
            "action": {"type": "uri", "uri": link} if link else None
        }

    if link:
        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#00BFFF",
                    "height": "sm",
                    "action": {"type": "uri", "label": "詳細を見る", "uri": link}
                }
            ]
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
    if not raw_items:
        print("8/25の対象データが見つかりませんでした。")
        return

    # ★安全対策：LINE APIの上限(12件)を超えないよう最大5件へ制御
    send_targets = raw_items[:MAX_NOTIFY_LIMIT]
    print(f"★8/25の対象データ {len(raw_items)}件中、安全枠として{len(send_targets)}件を送信対象とします。")

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
        alt_text=f"【8/25確認テスト】({len(send_targets)}件)",
        contents=FlexContainer.from_dict(flex_container_dict)
    )

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            broadcast_request = BroadcastRequest(messages=[flex_message])
            line_bot_api.broadcast(broadcast_request)
        
        print(f"★8/25のデータ {len(send_targets)}件をカルーセル形式で正常送信しました。")

    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    main()

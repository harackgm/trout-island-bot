import os
import sqlite3
import requests
from bs4 import BeautifulSoup
import re

# 設定項目
TARGET_URL = "http://troutisland.shop-pro.jp/"
DB_PATH = "products.db"

# GitHub Secretsから環境変数を取得
LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")  # 自分専用のユーザーID

def init_db():
    """データベースの初期化"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notified_products (
            item_key TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_notified(item_key):
    """通知済みか確認"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM notified_products WHERE item_key = ?', (item_key,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_notified(item_key):
    """通知済みキーとして保存"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO notified_products (item_key) VALUES (?)', (item_key,))
    conn.commit()
    conn.close()

def get_product_image(product_url):
    """商品ページから画像URLを抽出（見つからなければNone）"""
    if not product_url or product_url == TARGET_URL:
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(product_url, headers=headers, timeout=5)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, "html.parser")
        
        # og:image タグから高画質画像を取得、無ければimgタグから検索
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]
            
        img_tag = soup.find("img", src=re.compile(r'/upload/save_image/|/product/'))
        if img_tag and img_tag.get("src"):
            return requests.compat.urljoin(product_url, img_tag["src"])
    except Exception as e:
        print(f"画像取得エラー ({product_url}): {e}")
    return None

def send_individual_line_notification(title, url_link):
    """1件ごとに写真付きメッセージをLINEへ送信"""
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("エラー: LINEアクセストークンまたはユーザーIDが設定されていません。")
        return

    api_url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    
    # 画像URLを取得
    image_url = get_product_image(url_link)
    
    messages = []
    
    # 画像が存在すれば画像メッセージを追加（HTTPS必須）
    if image_url and image_url.startswith("https://"):
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url
        })
        
    # テキストメッセージ（商品名＋URL）
    message_text = f"【トラウトアイランド 新入荷】\n{title}"
    if url_link and url_link != TARGET_URL:
        message_text += f"\n\n{url_link}"
        
    messages.append({
        "type": "text",
        "text": message_text
    })

    payload = {
        "to": LINE_USER_ID,
        "messages": messages
    }
    
    response = requests.post(api_url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"送信成功: {title}")
        save_notified(title)
    else:
        print(f"送信失敗 [{response.status_code}]: {response.text}")

def main():
    init_db()
    print("トラウトアイランドの巡回チェック（写真付き個別通知モード）を開始します...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=10)
        response.encoding = response.apparent_encoding
    except Exception as e:
        print(f"Webサイトの取得に失敗しました: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    extracted_items = []
    
    for a_tag in soup.find_all("a", href=True):
        text = a_tag.get_text(strip=True)
        href = a_tag["href"]
        if re.search(r'\d{1,2}/\d{1,2}', text) or any(kw in text for kw in ["新入荷", "再入荷", "新色", "在庫更新", "ご予約"]):
            full_url = requests.compat.urljoin(TARGET_URL, href)
            for line in text.splitlines():
                line = line.strip()
                if line:
                    extracted_items.append((line, full_url))

    print(f"抽出された更新情報件数: {len(extracted_items)}件")

    seen = set()
    for title, url_link in extracted_items:
        if title in seen:
            continue
        seen.add(title)
        
        if not is_notified(title):
            print(f"新規検知: {title}")
            send_individual_line_notification(title, url_link)
        else:
            print(f"スキップ（通知済み）: {title}")

if __name__ == "__main__":
    main()

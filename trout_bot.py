import os
import sqlite3
import requests
from bs4 import BeautifulSoup

# 設定項目
TARGET_URL = "http://troutisland.shop-pro.jp/"
DB_PATH = "products.db"
LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

def init_db():
    """データベースの初期化"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notified_products (
            url TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_notified(url):
    """通知済みか確認"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM notified_products WHERE url = ?', (url,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_notified(url):
    """通知済みURLとして保存"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO notified_products (url) VALUES (?)', (url,))
    conn.commit()
    conn.close()

def send_line_notification(title, url_link):
    """1件ずつ標準的なWebプレビューが展開される形式で送信"""
    if not LINE_ACCESS_TOKEN:
        print("エラー: LINE_CHANNEL_ACCESS_TOKEN が設定されていません。")
        return

    api_url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    
    # 以前の表示形式（タイトル + URL）
    message_text = f"【新着・在庫更新】\n{title}\n\n{url_link}"
    
    payload = {
        "messages": [
            {
                "type": "text",
                "text": message_text
            }
        ]
    }
    response = requests.post(api_url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"送信成功: {title}")
    else:
        print(f"送信失敗: {response.status_code} {response.text}")

def main():
    init_db()
    print("トラウトアイランドの巡回チェックを開始します...")

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
    
    # 新着商品・在庫更新のリンクのみを正確に取得
    keywords = ["【新着・在庫更新】", "新入荷", "再入荷", "ご予約商品", "予約"]
    
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        text = a_tag.get_text(strip=True)

        if any(kw in text for kw in keywords) or "pid=" in href:
            full_url = requests.compat.urljoin(TARGET_URL, href)
            
            # トラウトアイランドの個別商品ページURLのみに限定
            if "pid=" in full_url and not is_notified(full_url):
                # タイトルの成形
                clean_title = text.replace("【新着・在庫更新】", "").strip()
                if not clean_title:
                    clean_title = "新着商品"
                
                # 画像1枚目の形式（1件につき1メッセージ送信）でLINEへ飛ばす
                send_line_notification(clean_title, full_url)
                save_notified(full_url)

if __name__ == "__main__":
    main()

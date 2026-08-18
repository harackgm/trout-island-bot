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

def send_line_notification(title, url_link):
    """指定したユーザーIDのみへ個別通知（Push Message）を送信"""
    if not LINE_ACCESS_TOKEN:
        print("エラー: LINE_CHANNEL_ACCESS_TOKEN が設定されていません。")
        return
    if not LINE_USER_ID:
        print("エラー: LINE_USER_ID が設定されていません。GitHub Secretsを確認してください。")
        return

    # broadcast から push へ変更して特定の自分だけに送る
    api_url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    
    if url_link:
        message_text = f"【トラウトアイランド 新入荷・在庫更新】\n{title}\n\n{url_link}"
    else:
        message_text = f"【トラウトアイランド 新入荷・在庫更新】\n{title}"
    
    payload = {
        "to": LINE_USER_ID,  # 自分だけに送信指定
        "messages": [
            {
                "type": "text",
                "text": message_text
            }
        ]
    }
    response = requests.post(api_url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"送信成功（自分のみ）: {title}")
    else:
        print(f"送信失敗: {response.status_code} {response.text}")

def main():
    init_db()
    print("トラウトアイランドの巡回チェック（自分専用テストモード）を開始します...")

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
    
    # ページ内のリンク・テキスト要素から更新情報を広範囲に抽出
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        text = a_tag.get_text(strip=True)

        # 「月/日」（例: 8/18）が含まれる、または「入荷」「予約」「更新」等のキーワードがある場合
        if re.search(r'\d{1,2}/\d{1,2}', text) or any(kw in text for kw in ["新入荷", "再入荷", "新色", "在庫更新", "ご予約"]):
            full_url = requests.compat.urljoin(TARGET_URL, href)
            
            # DBの重複判定キー
            item_key = text
            
            if not is_notified(item_key):
                send_line_notification(text, full_url)
                save_notified(item_key)

if __name__ == "__main__":
    main()

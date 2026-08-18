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
    """データベースの移行・マイグレーション"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notified_products (
            item_key TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute("PRAGMA table_info(notified_products)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if "item_key" not in columns:
        cursor.execute("ALTER TABLE notified_products ADD COLUMN item_key TEXT")
        cursor.execute("UPDATE notified_products SET item_key = url WHERE item_key IS NULL")
    
    conn.commit()
    conn.close()

def is_notified(item_key, url):
    """通知済みか確認"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM notified_products WHERE item_key = ? OR url = ?', (item_key, url))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_notified(item_key, url):
    """通知済みキーおよびURLとして保存"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO notified_products (item_key, url) VALUES (?, ?)', (item_key, url))
    except sqlite3.OperationalError:
        cursor.execute('INSERT OR IGNORE INTO notified_products (item_key) VALUES (?)', (item_key,))
    conn.commit()
    conn.close()

def send_line_notification(title, url_link):
    """指定したユーザーIDのみへ個別通知（Push Message）を送信"""
    if not LINE_ACCESS_TOKEN:
        print("エラー: LINE_CHANNEL_ACCESS_TOKEN が設定されていません。")
        return
    if not LINE_USER_ID:
        print("エラー: LINE_USER_ID が設定されていません。")
        return

    api_url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    
    message_text = f"【トラウトアイランド 新入荷・在庫更新】\n{title}"
    if url_link and url_link != TARGET_URL:
        message_text += f"\n\n{url_link}"
    
    payload = {
        "to": LINE_USER_ID,
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
        print(f"送信失敗 [{response.status_code}]: {response.text}")

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
    
    # ページ内のすべての行・要素から日付またはキーワードを含む文言を抽出
    extracted_items = []
    
    # 1. リンク付き要素の検証
    for a_tag in soup.find_all("a", href=True):
        text = a_tag.get_text(strip=True)
        href = a_tag["href"]
        if re.search(r'\d{1,2}/\d{1,2}', text) or any(kw in text for kw in ["新入荷", "再入荷", "新色", "在庫更新", "ご予約"]):
            full_url = requests.compat.urljoin(TARGET_URL, href)
            extracted_items.append((text, full_url))

    # 2. テキストのみ（リンク無し）要素の検証
    for element in soup.find_all(["td", "div", "p", "li"]):
        # 直下のテキストを取得
        text = element.get_text(strip=True)
        if re.search(r'\d{1,2}/\d{1,2}\s+\S+', text):
            # 長すぎる全体ブロックを除外するため、100文字以内の行のみ抽出
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            for line in lines:
                if re.search(r'\d{1,2}/\d{1,2}', line) and len(line) < 80:
                    extracted_items.append((line, TARGET_URL))

    print(f"抽出された更新情報件数: {len(extracted_items)}件")

    # 重複を除去して処理
    seen = set()
    for title, url_link in extracted_items:
        if title in seen:
            continue
        seen.add(title)
        
        if not is_notified(title, url_link):
            print(f"新規検知: {title}")
            send_line_notification(title, url_link)
            save_notified(title, url_link)
        else:
            print(f"スキップ（通知済み）: {title}")

if __name__ == "__main__":
    main()

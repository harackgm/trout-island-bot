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

def send_combined_line_notification(new_items):
    """複数の新規入荷情報を1通のLINEメッセージにまとめて送信"""
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("エラー: LINEアクセストークンまたはユーザーIDが設定されていません。")
        return

    api_url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    
    # メッセージ作成
    message_text = "【トラウトアイランド 新入荷・更新情報】\n"
    for title, url_link in new_items:
        message_text += f"\n・{title}"
        if url_link and url_link != TARGET_URL:
            message_text += f"\n  {url_link}"
    
    # LINE送信文字数上限（5000文字）に配慮してカット
    if len(message_text) > 4500:
        message_text = message_text[:4500] + "\n...(以下省略)"

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
        print(f"送信成功（まとめ送信 {len(new_items)}件）")
        for title, _ in new_items:
            save_notified(title)
    else:
        print(f"送信失敗 [{response.status_code}]: {response.text}")

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
    items_to_notify = []
    
    for title, url_link in extracted_items:
        if title in seen:
            continue
        seen.add(title)
        
        if not is_notified(title):
            print(f"新規検知: {title}")
            items_to_notify.append((title, url_link))
        else:
            print(f"スキップ（通知済み）: {title}")

    if items_to_notify:
        send_combined_line_notification(items_to_notify)
    else:
        print("新しい更新情報はありませんでした。")

if __name__ == "__main__":
    main()

import os
import sqlite3
import requests
from bs4 import BeautifulSoup

# 設定パラメータ
TARGET_URL = "http://troutisland.shop-pro.jp/"
DB_PATH = "products.db"

# トークンはコードに直書きせず、GitHub Secretsから環境変数として取得する
LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

def init_db():
    """通知済み商品を記録するSQLiteデータベースの初期化"""
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
    """商品がすでに通知済みか確認"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM notified_products WHERE url = ?', (url,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_notified(url):
    """通知済み商品をデータベースに保存"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO notified_products (url) VALUES (?)', (url,))
    conn.commit()
    conn.close()

def send_line_notification(message):
    """LINE Messaging APIを通じてブロードキャスト通知を送信"""
    if not LINE_ACCESS_TOKEN:
        print("エラー: LINE_CHANNEL_ACCESS_TOKEN が設定されていません。GitHub Secretsを確認してください。")
        return

    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    payload = {
        "messages": [
            {
                "type": "text",
                "text": message
            }
        ]
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print("LINE通知の送信に成功しました。")
    else:
        print(f"LINE通知の送信に失敗しました: Status {response.status_code}, Response: {response.text}")

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
    new_items = []

    # トラウトアイランドの新着・在庫更新キーワード判定
    keywords = ["【新着・在庫更新】", "新入荷", "再入荷", "予約", "ご予約"]
    
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        text = a_tag.get_text(strip=True)

        if any(kw in text for kw in keywords):
            full_url = requests.compat.urljoin(TARGET_URL, href)
            if not is_notified(full_url):
                new_items.append((text, full_url))

    if not new_items:
        print("新しい更新商品はありませんでした。")
        return

    # スマートなテキスト形式でメッセージを作成
    msg_lines = ["🆕【御徒町アイランド 新入荷・在庫更新情報】", "━━━━━━━━━━━━━━━━━━"]
    for title, url in new_items:
        msg_lines.append(f"🎣 {title}\n👉 {url}")
        save_notified(url)
    msg_lines.append("━━━━━━━━━━━━━━━━━━")

    full_message = "\n\n".join(msg_lines)
    send_line_notification(full_message)

if __name__ == "__main__":
    main()

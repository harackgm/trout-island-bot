import os
import sqlite3
import requests
import re
import hashlib
from urllib.parse import urljoin
from bs4 import BeautifulSoup

TARGET_URL = "https://troutisland.shop-pro.jp/"
DB_FILE = "products.db"

def init_and_reset_db():
    """既存のDBを一度削除し、クリーンな状態で再構築する"""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print("古い DB (products.db) を削除しました。")

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
    conn.close()

def generate_key(url, title):
    raw_str = f"{url}_{title}"
    return hashlib.md5(raw_str.encode('utf-8')).hexdigest()

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def force_https(url_str):
    if not url_str:
        return ""
    if url_str.startswith("http://"):
        return "https://" + url_str[7:]
    return url_str

def extract_updates(soup):
    items = []
    target_blocks = []
    for tag in soup.find_all(['td', 'div', 'p', 'table']):
        text = tag.get_text()
        if ('新入荷' in text or '在庫更新' in text) and not ('オススメ' in text or 'おすすめ' in text):
            target_blocks.append(tag)

    if not target_blocks:
        target_blocks = [soup]

    for block in target_blocks:
        a_tags = block.find_all('a', href=True)
        for a in a_tags:
            href = clean_text(a['href'])
            text = clean_text(a.get_text())

            if not href or 'mode=cate' in href or 'cart' in href or 'myaccount' in href or href in ['/', '#']:
                continue

            parent_text = clean_text(a.parent.get_text()) if a.parent else ""
            has_date = bool(re.search(r'\d{1,2}/\d{1,2}', text) or re.search(r'\d{1,2}/\d{1,2}', parent_text))

            if has_date and ('pid=' in href or 'shop-pro.jp' in href):
                full_url = force_https(urljoin(TARGET_URL, href))
                items.append((text, full_url))

    return items

def main():
    print("--- データベースの一括初期化処理を開始します ---")
    
    # DBをクリーン作成
    init_and_reset_db()

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=10)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"サイトアクセスエラー: {e}")
        return

    raw_items = extract_updates(soup)
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    registered_count = 0
    for title, url in raw_items:
        item_key = generate_key(url, title)
        c.execute('INSERT OR IGNORE INTO seen_items (item_key, url, title) VALUES (?, ?, ?)', (item_key, url, title))
        registered_count += 1
        
    conn.commit()
    conn.close()

    print(f"【成功】現在サイトにある全 {registered_count} 件の商品を既読データとして DB に一括登録しました。")
    print("※LINEへの通知処理は実行していません。")

if __name__ == "__main__":
    main()

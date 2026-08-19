import os
import sqlite3
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# LINE Messaging API v3 用のインポート
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)

# 環境変数から取得
CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
USER_ID = os.environ.get('LINE_USER_ID')
BASE_URL = 'https://troutisland.shop-pro.jp/'
DB_NAME = 'products.db'

def init_db():
    """データベースの初期化"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            url TEXT PRIMARY KEY,
            title TEXT
        )
    ''')
    conn.commit()
    conn.close()

def is_db_empty():
    """DBが空（初回実行）かどうかを判定"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM products')
    count = cursor.fetchone()[0]
    conn.close()
    return count == 0

def check_new_items():
    """新入荷＆在庫更新情報のテキストリンクをチェックする"""
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("エラー: LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が設定されていません。")
        return

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    
    print("巡回チェックを開始します...")
    try:
        response = requests.get(BASE_URL, timeout=10)
        response.encoding = response.apparent_encoding
    except Exception as e:
        print(f"サイトへのアクセスに失敗しました: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    first_run = is_db_empty()
    if first_run:
        print("【初回起動検知】現在の全商品を通知なしでデータベースに初期登録します...")

    new_items_found = 0
    links = soup.find_all('a', href=True)
    
    for a in links:
        href = a['href'].strip()
        title = a.get_text(strip=True)
        
        # 不要なナビゲーションや短すぎる・長すぎるタイトルを除外
        if not title or len(title) < 4 or len(title) > 100:
            continue
            
        if href in ['/', '#', 'javascript:void(0);'] or 'cart' in href or 'myaccount' in href:
            continue

        # 絶対パスURLを作成
        full_url = urljoin(BASE_URL, href)

        # 【最重要】LINEの送信要件を満たすため、必ず https:// に変換
        if full_url.startswith('http://'):
            full_url = full_url.replace('http://', 'https://', 1)
        elif not full_url.startswith('https://'):
            continue

        # DBに未登録のURLか確認
        cursor.execute('SELECT url FROM products WHERE url = ?', (full_url,))
        result = cursor.fetchone()
        
        if not result:
            # DBに新規登録
            cursor.execute('INSERT INTO products (url, title) VALUES (?, ?)', (full_url, title))
            conn.commit()
            
            if first_run:
                continue

            message_text = f"【新着・在庫更新】\n・{title}\n\n{full_url}"
            
            try:
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    push_message_request = PushMessageRequest(
                        to=USER_ID,
                        messages=[TextMessage(text=message_text)]
                    )
                    line_bot_api.push_message(push_message_request)
                    
                print(f"通知送信: {title}")
                new_items_found += 1
            except Exception as e:
                print(f"LINE API送信エラー: {e}")

    conn.close()
    
    if first_run:
        print("初期登録が完了しました。次回更新分よりLINE通知されます。")
    elif new_items_found == 0:
        print("新着商品はありませんでした。")
    else:
        print(f"{new_items_found}件の新着・更新を通知しました。")

if __name__ == '__main__':
    init_db()
    check_new_items()

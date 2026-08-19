import os
import sqlite3
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# LINE Messaging API v3
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
USER_ID = os.environ.get('LINE_USER_ID')
BASE_URL = 'http://troutisland.shop-pro.jp/'
DB_NAME = 'products.db'

def init_db():
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

def check_new_items():
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

    links = soup.find_all('a', href=True)
    
    target_item = None

    # HP上で最初に見つかる『/?pid=』付きの最新商品1件を取得
    for a in links:
        href = a['href'].strip()
        title = a.get_text(strip=True)
        
        if '/?pid=' in href and title and len(title) >= 2:
            full_url = urljoin(BASE_URL, href)
            target_item = (full_url, title)
            break  # 1件見つかったら即終了

    if target_item:
        full_url, title = target_item
        print(f"テスト対象商品を取得しました: {title}")
        
        # テスト通知を送信
        message_text = f"【動作テスト・最新更新】\n{title}\n\n{full_url}"
        
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                push_message_request = PushMessageRequest(
                    to=USER_ID,
                    messages=[TextMessage(text=message_text)]
                )
                line_bot_api.push_message(push_message_request)
                
            # 送信成功したらDBに保存（次回以降の重複通知を防止）
            cursor.execute('INSERT OR REPLACE INTO products (url, title) VALUES (?, ?)', (full_url, title))
            conn.commit()
            print("LINEへのテスト通知が成功しました！DBに登録完了。")
            
        except Exception as e:
            print(f"LINE API送信エラー: {e}")
    else:
        print("商品リンク（/?pid=）が見つかりませんでした。")

    conn.close()

if __name__ == '__main__':
    init_db()
    check_new_items()

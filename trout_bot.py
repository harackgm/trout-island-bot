import os
import sqlite3
import requests
import re
from urllib.parse import urljoin, quote
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
BASE_URL = 'https://troutisland.shop-pro.jp/'
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

def sanitize_string(text):
    if not text:
        return ""
    cleaned = re.sub(r'[\r\n\t]+', ' ', text)
    return cleaned.strip()

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

    for a in links:
        raw_href = a['href']
        raw_title = a.get_text()
        
        title = sanitize_string(raw_title)
        href = sanitize_string(raw_href)
        
        if not title or len(title) < 4 or len(title) > 100:
            continue
            
        if href in ['/', '#', 'javascript:void(0);'] or 'cart' in href or 'myaccount' in href:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url.startswith('http://'):
            full_url = full_url.replace('http://', 'https://', 1)
            
        if not full_url.startswith('https://'):
            continue

        # URLパラメータに含まれる特殊文字（&など）のエラー回避処理
        # 安全な文字列構造（https://...）にサニタイズ
        clean_url = full_url.replace('&amp;', '&')

        target_item = (clean_url, title)
        break

    if target_item:
        full_url, title = target_item
        print(f"テスト対象（最新の更新情報）を取得しました: {title}")
        print(f"送信URL: {full_url}")
        
        # URLをプレーンテキストメッセージとして送信
        message_text = f"【動作テスト・最新更新】\n・{title}\n\n{full_url}"
        
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                push_message_request = PushMessageRequest(
                    to=USER_ID,
                    messages=[TextMessage(text=message_text)]
                )
                line_bot_api.push_message(push_message_request)
                
            cursor.execute('INSERT OR REPLACE INTO products (url, title) VALUES (?, ?)', (full_url, title))
            conn.commit()
            print("LINEへのテスト通知が成功しました！DBに登録完了。")
            
        except Exception as e:
            print(f"LINE API送信エラー: {e}")
    else:
        print("更新リンクが見つかりませんでした。")

    conn.close()

if __name__ == '__main__':
    init_db()
    check_new_items()

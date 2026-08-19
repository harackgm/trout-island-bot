import os
import sqlite3
import requests
import re
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

def clean_text(text):
    """改行・タブ・連続空白をすべて1つのスペースに変換してサニタイズ"""
    if not text:
        return ""
    # 改行(\r, \n)やタブ(\t)をスペースに置換
    text = re.sub(r'[\r\n\t]+', ' ', text)
    # 連続するスペースを1つに縮小
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def check_new_items():
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("エラー: LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が設定されていません。")
        return

    # 前後の空白や改行を除去
    token = CHANNEL_ACCESS_TOKEN.strip() if CHANNEL_ACCESS_TOKEN else ""
    user_id = USER_ID.strip() if USER_ID else ""

    configuration = Configuration(access_token=token)
    
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
        
        # 文字列の完全クレンジング
        title = clean_text(raw_title)
        href = clean_text(raw_href)
        
        if not title or len(title) < 4 or len(title) > 100:
            continue
            
        if href in ['/', '#', 'javascript:void(0);'] or 'cart' in href or 'myaccount' in href:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url.startswith('http://'):
            full_url = full_url.replace('http://', 'https://', 1)
            
        if not full_url.startswith('https://'):
            continue

        target_item = (full_url, title)
        break

    if target_item:
        full_url, title = target_item
        print(f"テスト対象を取得しました: {repr(title)}")
        print(f"送信URL: {repr(full_url)}")
        
        # メッセージ本文（改行は \n のみを使用）
        message_text = f"【動作テスト・最新更新】\n・{title}\n\n{full_url}"
        
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                push_message_request = PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=message_text)]
                )
                line_bot_api.push_message(push_message_request)
                
            cursor.execute('INSERT OR REPLACE INTO products (url, title) VALUES (?, ?)', (full_url, title))
            conn.commit()
            print("LINEへのテスト通知が成功しました！DBに登録完了。")
            
        except Exception as e:
            print(f"LINE API送信エラーが発生しました: {e}")
    else:
        print("更新リンクが見つかりませんでした。")

    conn.close()

if __name__ == '__main__':
    init_db()
    check_new_items()

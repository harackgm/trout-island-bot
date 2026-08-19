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
    if not text:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def check_new_items():
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("エラー: LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が設定されていません。")
        return

    token = CHANNEL_ACCESS_TOKEN.strip()
    user_id = USER_ID.strip()

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
    
    new_items_found = 0

    for a in links:
        raw_href = a['href']
        raw_title = a.get_text()
        
        title = clean_text(raw_title)
        href = clean_text(raw_href)
        
        # 【重要】個別商品ページ（/?pid=）以外はLINEのプレビュー生成エラーになるためスキップ
        if '/?pid=' not in href:
            continue
            
        if not title or len(title) < 2:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url.startswith('http://'):
            full_url = full_url.replace('http://', 'https://', 1)

        # DB未登録の商品かチェック
        cursor.execute('SELECT url FROM products WHERE url = ?', (full_url,))
        if cursor.fetchone():
            continue

        # 未登録の個別商品を発見した場合のみLINE送信
        message_text = f"【新着・在庫更新】\n{title}\n\n{full_url}"
        
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                push_message_request = PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=message_text)]
                )
                line_bot_api.push_message(push_message_request)
                
            # 送信成功した時だけ DB に保存
            cursor.execute('INSERT INTO products (url, title) VALUES (?, ?)', (full_url, title))
            conn.commit()
            print(f"通知成功: {title}")
            new_items_found += 1
            
        except Exception as e:
            print(f"LINE API送信エラー ({title}): {e}")

    conn.close()
    
    if new_items_found == 0:
        print("新着・未通知の個別商品は見つかりませんでした。")
    else:
        print(f"{new_items_found}件の個別商品をLINEへ通知しました。")

if __name__ == '__main__':
    init_db()
    check_new_items()

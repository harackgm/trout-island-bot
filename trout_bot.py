import os
import sqlite3
import requests
from bs4 import BeautifulSoup
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

# 環境変数からLINEのアクセストークンを取得
CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
TARGET_URL = 'http://troutisland.shop-pro.jp/'
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

def check_new_items():
    """新入荷＆在庫更新情報のテキストリンクをチェックする"""
    if not CHANNEL_ACCESS_TOKEN:
        print("エラー: LINE_CHANNEL_ACCESS_TOKEN が設定されていません。")
        return

    line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
    
    print("巡回チェックを開始します...")
    try:
        response = requests.get(TARGET_URL, timeout=10)
        response.encoding = response.apparent_encoding
    except Exception as e:
        print(f"サイトへのアクセスに失敗しました: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # データベース接続
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    new_items_found = 0

    # 「新入荷＆在庫更新情報」などのページ内リンクを探索
    links = soup.find_all('a', href=True)
    
    for a in links:
        href = a['href']
        title = a.get_text(strip=True)
        
        # 商品詳細ページ（/?pid= を含むURL）かつ、タイトルが存在するリンクを抽出
        if '/?pid=' in href and title:
            # 相対パスを絶対パス（http...）に変換
            if href.startswith('/'):
                href = TARGET_URL.rstrip('/') + href
            elif not href.startswith('http'):
                continue
                
            # DBに未登録のURLか確認
            cursor.execute('SELECT url FROM products WHERE url = ?', (href,))
            result = cursor.fetchone()
            
            if not result:
                # 新規登録
                cursor.execute('INSERT INTO products (url, title) VALUES (?, ?)', (href, title))
                conn.commit()
                
                # LINEへ通知を送信
                message = f"【新着・在庫更新】\n{title}\n\n{href}"
                try:
                    line_bot_api.broadcast(TextSendMessage(text=message))
                    print(f"通知送信: {title}")
                    new_items_found += 1
                except LineBotApiError as e:
                    print(f"LINE通知エラー: {e}")

    conn.close()
    
    if new_items_found == 0:
        print("新着商品はありませんでした。")
    else:
        print(f"{new_items_found}件の新着・更新を通知しました。")

if __name__ == '__main__':
    init_db()
    check_new_items()

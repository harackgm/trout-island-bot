import os
import sqlite3
import requests
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

    # LINE v3 APIクライアントの設定
    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    
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
    
    # 初回実行（DBが空）かどうかを判定
    first_run = is_db_empty()
    if first_run:
        print("【初回起動検知】現在の全商品を通知なしでデータベースに初期登録します...")

    new_items_found = 0

    # ページ内の全リンクを取得
    links = soup.find_all('a', href=True)
    
    for a in links:
        href = a['href']
        title = a.get_text(strip=True)
        
        # 【判定ロジックの改善】
        # トップページの余計なナビリンク等を除外し、意味のある更新リンク（文字数4〜100文字）を抽出
        if title and 4 <= len(title) <= 100:
            # トップページ自身へのリンクや無関係なメニューを除外
            if href in ['/', '#', 'javascript:void(0);'] or 'cart' in href or 'myaccount' in href:
                continue
                
            # 相対パスを絶対パス（http...）に変換
            if href.startswith('/'):
                full_url = TARGET_URL.rstrip('/') + href
            elif href.startswith('http'):
                full_url = href
            else:
                continue
                
            # DBに未登録のURLか確認
            cursor.execute('SELECT url FROM products WHERE url = ?', (full_url,))
            result = cursor.fetchone()
            
            if not result:
                # 新規登録
                cursor.execute('INSERT INTO products (url, title) VALUES (?, ?)', (full_url, title))
                conn.commit()
                
                # 初回実行時はLINE送信をスキップ
                if first_run:
                    continue

                # 送信用テキストを作成
                message_text = f"【新着・在庫更新】\n・{title}\n\n{full_url}"
                
                # LINE v3 APIによるPush送信
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

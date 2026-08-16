import os
import sqlite3
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from linebot import LineBotApi
from linebot.models import (
    FlexSendMessage, BubbleContainer, ImageComponent, 
    BoxComponent, TextComponent, ButtonComponent, URIAction
)

# ==========================================
# 設定情報
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = "DaSpwYl/29Wq4kziLqIhAOvIilhf14Lh6wy+CMDreWMSunuytjsO89+8XVcC0zZ8i06k1FQCAWcq9qCzvv5Ko9KrmDr40/AViejAftvfX+9L6BspirclA/rS3SJEKVtodr8ur3tJJU+5itanOvF4bgdB04t89/1O/w1cDnyilFU="
TARGET_URL = "http://troutisland.shop-pro.jp/"
DB_FILE = "products.db"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# ==========================================
# 1. データベース設定 (重複防止用)
# ==========================================
def init_db():
    """データベースの初期化"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT UNIQUE NOT NULL,
            img_url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_notified(link):
    """通知済みかどうかチェック"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM products WHERE link = ?", (link,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_product(title, link, img_url):
    """新商品をデータベースに保存"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO products (title, link, img_url) VALUES (?, ?, ?)",
            (title, link, img_url)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # 既に存在する場合は無視
    conn.close()

# ==========================================
# 2. LINEメッセージ作成 (Flex Message)
# ==========================================
def create_flex_message(title, link, img_url, header_text="【新着入荷】"):
    """写真・タイトル・ボタン付きのカード型メッセージを作成"""
    return BubbleContainer(
        hero=ImageComponent(
            url=img_url,
            size="full",
            aspect_ratio="20:13",
            aspect_mode="cover"
        ),
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(
                    text=header_text,
                    weight="bold",
                    color="#1DB446",
                    size="sm"
                ),
                TextComponent(
                    text=title,
                    weight="bold",
                    size="md",
                    wrap=True
                )
            ]
        ),
        footer=BoxComponent(
            layout="vertical",
            spacing="sm",
            contents=[
                ButtonComponent(
                    style="link",
                    height="sm",
                    action=URIAction(label="商品ページを見る", uri=link)
                )
            ]
        )
    )

# ==========================================
# 3. サイト巡回 & 新着チェック処理
# ==========================================
def check_new_products():
    """HPを監視して新着があれば全友だちにLINE一括送信"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        response = requests.get(TARGET_URL, headers=headers)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"サイト取得エラー: {e}")
        return

    # おすすめ商品・新着エリアから取得
    items = []
    for item_box in soup.find_all("li", class_="product_item"):
        title_tag = item_box.find("a")
        img_tag = item_box.find("img")
        
        if title_tag and img_tag:
            title = title_tag.get_text(strip=True)
            link = urljoin(TARGET_URL, title_tag.get("href"))
            img_url = urljoin(TARGET_URL, img_tag.get("src"))
            items.append({"title": title, "link": link, "img_url": img_url})

    # 未通知の商品を検出してブロードキャスト送信
    new_count = 0
    for item in reversed(items):  # 古い順に処理してDB格納
        if not is_notified(item["link"]):
            # DBに保存
            save_product(item["title"], item["link"], item["img_url"])
            
            # LINE送信 (broadcast)
            bubble = create_flex_message(item["title"], item["link"], item["img_url"])
            flex_msg = FlexSendMessage(
                alt_text=f"新着入荷: {item['title']}", 
                contents=bubble
            )
            line_bot_api.broadcast(flex_msg)
            print(f"新着通知送信: {item['title']}")
            new_count += 1
            
    if new_count == 0:
        print("新着商品はありませんでした。")

# ==========================================
# 実行メイン処理
# ==========================================
if __name__ == "__main__":
    init_db()
    print("巡回チェックを開始します...")
    check_new_products()

import os
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

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
USER_ID = os.environ.get('LINE_USER_ID', '').strip()
TARGET_URL = "https://troutisland.shop-pro.jp/"

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

def test_single_send():
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("エラー: Secretsが設定されていません。")
        return

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=10)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"サイトアクセスエラー: {e}")
        return

    target_item = None
    links = soup.find_all('a', href=True)

    for a in links:
        title = clean_text(a.get_text())
        href = clean_text(a['href'])

        if not title or len(title) < 4 or len(title) > 100:
            continue
        if href in ['/', '#', 'javascript:void(0);'] or 'cart' in href or 'myaccount' in href:
            continue

        full_url = force_https(urljoin(TARGET_URL, href))
        target_item = (title, full_url)
        break

    if not target_item:
        print("更新対象が見つかりませんでした。")
        return

    title, link = target_item
    print(f"テスト対象を取得しました: {title}")
    print(f"送信URL: {link}")

    # シンプルなテキスト本文を作成
    message_text = f"【テスト通知】\n{title}\n\n{link}"

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            text_msg = TextMessage(text=message_text)
            push_message_request = PushMessageRequest(
                to=USER_ID,
                messages=[text_msg]
            )
            line_bot_api.push_message(push_message_request)
        print("★テキストテスト送信成功！LINEをご確認ください。")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    test_single_send()

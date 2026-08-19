import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# LINE Messaging API v3
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    FlexSendMessage,
    FlexContainer
)

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
USER_ID = os.environ.get('LINE_USER_ID', '').strip()
TARGET_URL = "https://troutisland.shop-pro.jp/"

def create_flex_message(title, link, img_url):
    if link.startswith("http://"):
        link = link.replace("http://", "https://", 1)
    if img_url.startswith("http://"):
        img_url = img_url.replace("http://", "https://", 1)

    return {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": img_url,
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "【テスト通知】",
                    "weight": "bold",
                    "color": "#1DB446",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": title,
                    "weight": "bold",
                    "size": "md",
                    "wrap": True
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "商品ページを見る",
                        "uri": link
                    }
                }
            ]
        }
    }

def test_single_send():
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("エラー: Secretsが設定されていません。")
        return

    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(TARGET_URL, headers=headers, timeout=10)
    response.encoding = response.apparent_encoding
    soup = BeautifulSoup(response.text, "html.parser")

    # トップページの先頭1件を取得
    item_box = soup.find("li", class_="product_item")
    if not item_box:
        print("商品が見つかりませんでした。")
        return

    title_tag = item_box.find("a")
    img_tag = item_box.find("img")

    title = title_tag.get_text(strip=True)
    link = urljoin(TARGET_URL, title_tag.get("href"))
    img_url = urljoin(TARGET_URL, img_tag.get("src"))

    print(f"テスト対象を取得しました: {title}")

    # DBを無視して1件送信
    flex_json = create_flex_message(title, link, img_url)
    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            flex_container = FlexContainer.from_dict(flex_json)
            flex_msg = FlexSendMessage(
                alt_text=f"テスト通知: {title}", 
                contents=flex_container
            )
            push_message_request = PushMessageRequest(
                to=USER_ID,
                messages=[flex_msg]
            )
            line_bot_api.push_message(push_message_request)
        print("★テスト送信成功！LINEをご確認ください。")
    except Exception as e:
        print(f"★送信エラー: {e}")

if __name__ == "__main__":
    test_single_send()

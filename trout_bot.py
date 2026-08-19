import os

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

def diagnose():
    print("--- 設定値診断 ---")
    print(f"TOKEN設定の有無: {'あり' if CHANNEL_ACCESS_TOKEN else 'なし'}")
    print(f"USER_ID設定の有無: {'あり' if USER_ID else 'なし'}")
    print(f"USER_IDの文字数: {len(USER_ID)}文字")
    
    if USER_ID:
        print(f"USER_IDの先頭3文字: {USER_ID[:3]}")
        if USER_ID.startswith("@"):
            print("★警告: USER_IDにボットのID（@...）が設定されている可能性があります。")
        elif not USER_ID.startswith("U"):
            print("★警告: USER_IDは通常『U』から始まります。設定値をご確認ください。")

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            text_msg = TextMessage(text="接続テスト成功です！")
            push_message_request = PushMessageRequest(
                to=USER_ID,
                messages=[text_msg]
            )
            line_bot_api.push_message(push_message_request)
        print("★接続テスト成功！LINEへ届きました。")
    except Exception as e:
        print(f"★送信エラー詳細: {e}")

if __name__ == "__main__":
    diagnose()

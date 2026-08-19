import os
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
USER_ID = os.environ.get('LINE_USER_ID', '').strip()

def test_send():
    print(f"--- 認証情報チェック ---")
    print(f"TOKEN設定有無: {bool(CHANNEL_ACCESS_TOKEN)} (文字数: {len(CHANNEL_ACCESS_TOKEN)})")
    print(f"USER_ID設定有無: {bool(USER_ID)} (文字数: {len(USER_ID)})")
    
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        print("エラー: Secretsが取得できていません。")
        return

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            push_message_request = PushMessageRequest(
                to=USER_ID,
                messages=[TextMessage(text="【テスト】LINE送信疎通テスト成功")]
            )
            line_bot_api.push_message(push_message_request)
        print("★成功: LINEへの送信が成功しました！")
    except Exception as e:
        print(f"★失敗: LINE APIエラー詳細 -> {e}")

if __name__ == '__main__':
    test_send()

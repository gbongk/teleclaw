"""PostToolUse 훅: mcp__emulator-test__screenshot 후 텔레그램 자동 전송."""
import json
import subprocess
import sys
import re

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    tool_name = data.get("tool_name", "")
    if tool_name != "mcp__emulator-test__screenshot":
        return

    # tool_response에서 파일 경로 추출
    response = data.get("tool_response", "")
    if isinstance(response, dict):
        response = json.dumps(response)

    # "saved: /path/to/file.jpg (44KB, ...)" 패턴에서 경로 추출
    match = re.search(r"saved:\s*(.+?)\s*\(", str(response))
    if not match:
        return

    file_path = match.group(1).strip()

    # session_id에서 프로젝트 추정 (caption용)
    session_id = data.get("session_id", "")
    caption = f"[Screenshot] {file_path}"

    # MCP 도구 직접 호출 대신, 텔레그램 MCP 서버에 직접 요청
    # relay-tool-use가 이미 텔레그램으로 도구 사용을 알리므로,
    # 여기서는 이미지만 전송
    try:
        # telegram-sender MCP 서버의 send_image를 직접 호출
        # MCP 서버는 stdin/stdout 프로토콜이라 직접 호출 불가
        # 대신 Python requests로 텔레그램 API 직접 호출
        import os
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "8510879138")

        if not bot_token:
            # config.py에서 현재 프로젝트의 봇 토큰 가져오기
            sys.path.insert(0, "D:/workspace/supervisor/hub")
            try:
                from config import PROJECTS, CHAT_ID
                chat_id = CHAT_ID
                # CWD 기반으로 프로젝트 찾기
                cwd = os.getcwd().replace("\\", "/").rstrip("/")
                for name, info in PROJECTS.items():
                    if cwd.startswith(info["cwd"]):
                        bot_token = info["bot_token"]
                        caption = f"[{name}] {file_path}"
                        break
                if not bot_token:
                    # 첫 번째 프로젝트의 토큰 사용
                    first = list(PROJECTS.values())[0]
                    bot_token = first["bot_token"]
            except Exception:
                return

        if not bot_token:
            return

        import urllib.request
        import urllib.parse

        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        boundary = "----FormBoundary7MA4YWxkTrZu0gW"

        with open(file_path, "rb") as f:
            file_data = f.read()

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
            f"{chat_id}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="caption"\r\n\r\n'
            f"{caption}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo"; filename="screenshot.jpg"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=10)

    except Exception:
        pass


if __name__ == "__main__":
    main()

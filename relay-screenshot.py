"""PostToolUse 훅: mcp__emulator-test__screenshot 후 텔레그램 자동 전송."""
import json
import os
import re
import sys

_SUPERVISOR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SUPERVISOR_DIR)
from relay_common import get_config, send_telegram_photo


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    tool_name = data.get("tool_name", "")
    if tool_name != "mcp__emulator-test__screenshot":
        return

    response = data.get("tool_response", "")
    if isinstance(response, dict):
        response = json.dumps(response)

    match = re.search(r"saved:\s*(.+?)\s*\(", str(response))
    if not match:
        return

    file_path = match.group(1).strip()
    if not os.path.exists(file_path):
        return

    config = get_config()
    if not config:
        return
    bot_token, chat_id, bot_name = config
    send_telegram_photo(bot_token, chat_id, file_path, caption=f"[{bot_name}] {file_path}")


if __name__ == "__main__":
    main()

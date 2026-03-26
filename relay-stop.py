#!/usr/bin/env python3
"""Stop hook: Claude 응답 완료 시 텍스트를 텔레그램으로 중계"""
import json
import os
import sys

_SUPERVISOR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SUPERVISOR_DIR)
from relay_common import get_config, is_relay_enabled, is_supervised_session, send_telegram

LOG = os.path.join(_SUPERVISOR_DIR, "logs", "relay-stop-debug.log")

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    try:
        with open(LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > 500:
            with open(LOG, "w", encoding="utf-8") as f:
                f.writelines(lines[-300:])
    except Exception:
        pass

def should_skip(hook_data):
    msg = hook_data.get("last_assistant_message", "")
    skip_patterns = ["wait_for_message"]
    return any(p in msg for p in skip_patterns)

def main():
    log("--- start ---")
    config = get_config()
    if not config:
        log("no config")
        return
    log("config ok")

    bot_token, chat_id, bot_name = config
    bot_id = bot_token.split(":")[0]

    if not is_relay_enabled(bot_id, chat_id):
        log("relay disabled")
        return

    hook_data = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    log(f"stdin: {hook_data[:200]}")
    if not hook_data:
        log("no stdin")
        return

    try:
        data = json.loads(hook_data)
    except json.JSONDecodeError:
        log("json error")
        return

    if not is_supervised_session(data.get("session_id")):
        log("not supervised")
        return

    if should_skip(data):
        log("skipped")
        return

    message = data.get("last_assistant_message", "")
    log(f"message: {message[:100]}")
    if not message or not message.strip():
        log("empty message")
        return

    if len(message) > 500:
        message = message[:500] + "..."

    text = f"[{bot_name}] {message}"

    if len(text) > 4000:
        text = text[:4000] + "..."

    log(f"sending: {text[:100]}")
    send_telegram(bot_token, chat_id, text)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"exception: {e}")

#!/usr/bin/env python3
"""Stop hook: Claude 응답 완료 시 텍스트를 텔레그램으로 중계"""
import json
import os
import sys
import urllib.request
import urllib.error

LOG = "D:/workspace/mcp/logs/relay-stop-debug.log"

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    # 로그 크기 제한 (500줄)
    try:
        with open(LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > 500:
            with open(LOG, "w", encoding="utf-8") as f:
                f.writelines(lines[-300:])
    except Exception:
        pass

def get_config():
    mcp_file = os.path.join(os.getcwd(), ".mcp.json")
    if not os.path.exists(mcp_file):
        return None
    with open(mcp_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    for name, srv in data.get("mcpServers", {}).items():
        env = srv.get("env", {})
        token = env.get("TELEGRAM_BOT_TOKEN")
        chat_id = env.get("TELEGRAM_CHAT_ID")
        if token and chat_id:
            bot_name = env.get("TELEGRAM_BOT_NAME", "Claude")
            return token, chat_id, bot_name
    return None

def is_relay_enabled(bot_id, chat_id):
    flag = f"D:/workspace/mcp/telegram/relay_enabled_{bot_id}_{chat_id}.flag"
    return os.path.exists(flag)

def is_supervised_session(session_id):
    """supervisor가 관리하는 세션인지 확인"""
    if not session_id:
        return False
    status_file = "D:/workspace/mcp/logs/supervisor_status.json"
    if not os.path.exists(status_file):
        return True
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        sessions_dir = "C:/Users/kok34/.claude/sessions"
        my_pid = None
        for sf_name in os.listdir(sessions_dir):
            sf_path = os.path.join(sessions_dir, sf_name)
            try:
                with open(sf_path, "r") as sf:
                    sd = json.load(sf)
                if sd.get("sessionId") == session_id:
                    my_pid = sd.get("pid")
                    break
            except Exception:
                continue
        if not my_pid:
            return False
        for name, sess in data.get("sessions", {}).items():
            if sess.get("pid") == my_pid:
                return True
        return False
    except Exception:
        return True

def should_skip(hook_data):
    msg = hook_data.get("last_assistant_message", "")
    skip_patterns = ["wait_for_message"]
    return any(p in msg for p in skip_patterns)

def send_telegram(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        log(f"send ok: {resp.status}")
    except Exception as e:
        log(f"send error: {e}")

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

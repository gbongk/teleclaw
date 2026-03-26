"""relay 훅 공통 유틸 — relay-stop.py, relay-tool-use.py에서 공유."""

import json
import os
import urllib.request

_SUPERVISOR_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_SUPERVISOR_DIR, "data")
LOGS_DIR = os.path.join(_SUPERVISOR_DIR, "logs")
STATUS_FILE = os.path.join(LOGS_DIR, "hub_status.json")
SESSIONS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "sessions")


def get_config():
    """현재 디렉토리의 .mcp.json에서 텔레그램 봇 설정을 읽는다.
    Returns: (bot_token, chat_id, bot_name) 튜플. 설정이 없으면 None."""
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
    # DB 체크 우선, 없으면 flag 파일 체크 (듀얼)
    try:
        import sys
        sys.path.insert(0, os.path.join(_SUPERVISOR_DIR, "hub"))
        from state_db import is_relay_enabled as db_check
        if db_check(bot_id, chat_id):
            return True
    except Exception:
        pass
    return os.path.exists(os.path.join(DATA_DIR, f"relay_enabled_{bot_id}_{chat_id}.flag"))


def is_supervised_session(session_id):
    """TeleClaw가 관리하는 세션인지 확인"""
    if not session_id:
        return False
    if not os.path.exists(STATUS_FILE):
        return True
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        my_pid = None
        if os.path.isdir(SESSIONS_DIR):
            for sf_name in os.listdir(SESSIONS_DIR):
                try:
                    with open(os.path.join(SESSIONS_DIR, sf_name), "r") as sf:
                        sd = json.load(sf)
                    if sd.get("sessionId") == session_id:
                        my_pid = sd.get("pid")
                        break
                except Exception:
                    continue
        if not my_pid:
            return False
        for sess in data.get("sessions", {}).values():
            if sess.get("pid") == my_pid:
                return True
        return False
    except Exception:
        return True


def _send_telegram_multipart(bot_token, chat_id, field, file_path, caption=""):
    """공통 multipart 전송 (urllib, 훅용 경량)."""
    import mimetypes
    boundary = "----RelayBoundary"
    body = b""
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode()
    if caption:
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode()
    mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    filename = os.path.basename(file_path)
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
    with open(file_path, "rb") as f:
        body += f.read()
    body += f"\r\n--{boundary}--\r\n".encode()
    endpoint = "sendPhoto" if field == "photo" else "sendDocument"
    url = f"https://api.telegram.org/bot{bot_token}/{endpoint}"
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"[relay] 파일 전송 실패: {e}", file=__import__('sys').stderr, flush=True)


def send_telegram_photo(bot_token, chat_id, photo_path, caption=""):
    """텔레그램으로 이미지 전송 (urllib, 훅용)."""
    _send_telegram_multipart(bot_token, chat_id, "photo", photo_path, caption)


def send_telegram_file(bot_token, chat_id, file_path, caption=""):
    """텔레그램으로 파일 전송 (urllib, 훅용)."""
    _send_telegram_multipart(bot_token, chat_id, "document", file_path, caption)


def send_telegram(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": text, "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[relay] 텔레그램 전송 실패: {e}", file=__import__('sys').stderr, flush=True)

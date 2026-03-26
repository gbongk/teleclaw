#!/usr/bin/env python3
"""텔레그램으로 이미지/파일 전송. 세션에서 직접 호출 가능.

Usage:
    python D:/workspace/supervisor/send_telegram.py photo <path> [caption]
    python D:/workspace/supervisor/send_telegram.py file  <path> [caption]
"""
import json, os, sys, urllib.request

CHAT_ID = "8510879138"

def get_telegram_config():
    """슈퍼바이저 config.py에서 cwd 기반으로 bot_token 매칭."""
    cwd = os.getcwd().replace("\\", "/").rstrip("/")
    config_path = os.path.join(os.path.dirname(__file__), "hub", "config.py")
    if os.path.exists(config_path):
        ns = {"os": os}
        with open(config_path, "r", encoding="utf-8") as f:
            exec(f.read(), ns)
        projects = ns.get("PROJECTS", {})
        for name, cfg in projects.items():
            proj_cwd = cfg.get("cwd", "").replace("\\", "/").rstrip("/")
            if cwd == proj_cwd or cwd.startswith(proj_cwd + "/"):
                return cfg["bot_token"], ns.get("CHAT_ID", CHAT_ID)
    # fallback: .mcp.json
    mcp_file = os.path.join(os.getcwd(), ".mcp.json")
    if os.path.exists(mcp_file):
        with open(mcp_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for srv in data.get("mcpServers", {}).values():
            env = srv.get("env", {})
            token = env.get("TELEGRAM_BOT_TOKEN")
            chat_id = env.get("TELEGRAM_CHAT_ID")
            if token and chat_id:
                return token, chat_id
    return None

def send(kind, bot_token, chat_id, path, caption=""):
    import mimetypes
    boundary = "----SendBoundary"
    body = b""
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode()
    if caption:
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode()
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    filename = os.path.basename(path)
    field = "photo" if kind == "photo" else "document"
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
    with open(path, "rb") as f:
        body += f.read()
    body += f"\r\n--{boundary}--\r\n".encode()

    endpoint = "sendPhoto" if kind == "photo" else "sendDocument"
    url = f"https://api.telegram.org/bot{bot_token}/{endpoint}"
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(req, timeout=30)
    print(f"전송 완료: {kind} {filename}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: send_telegram.py <photo|file> <path> [caption]")
        sys.exit(1)
    kind = sys.argv[1]
    path = sys.argv[2]
    caption = sys.argv[3] if len(sys.argv) > 3 else ""
    if kind not in ("photo", "file"):
        print("첫 인자는 photo 또는 file")
        sys.exit(1)
    if not os.path.exists(path):
        print(f"파일 없음: {path}")
        sys.exit(1)
    cfg = get_telegram_config()
    if not cfg:
        print("텔레그램 설정을 찾을 수 없음 (config.py, .mcp.json 모두 실패)")
        sys.exit(1)
    send(kind, cfg[0], cfg[1], path, caption)

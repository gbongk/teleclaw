#!/usr/bin/env python3
"""PostToolUse hook: 도구 사용 + Claude 중간 텍스트를 텔레그램으로 중계."""
import json
import os
import sys

import urllib.request

STATE_DIR = "D:/workspace/mcp/telegram"

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
    return os.path.exists(f"{STATE_DIR}/relay_enabled_{bot_id}_{chat_id}.flag")

def is_supervised_session(session_id):
    if not session_id:
        return False
    status_file = "D:/workspace/mcp/logs/supervisor_status.json"
    if not os.path.exists(status_file):
        return True
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            sup = json.load(f)
        sessions_dir = "C:/Users/kok34/.claude/sessions"
        my_pid = None
        for sf_name in os.listdir(sessions_dir):
            try:
                with open(os.path.join(sessions_dir, sf_name), "r") as sf:
                    sd = json.load(sf)
                if sd.get("sessionId") == session_id:
                    my_pid = sd.get("pid")
                    break
            except Exception:
                continue
        if not my_pid:
            return False
        for sess in sup.get("sessions", {}).values():
            if sess.get("pid") == my_pid:
                return True
        return False
    except Exception:
        return True

def send_telegram(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": text, "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def summarize(tool_name, tool_input):
    if isinstance(tool_input, dict):
        get = tool_input.get
    else:
        get = lambda k, d="": d

    if tool_name in ("Read", "Edit", "Write"):
        return f"{tool_name}: {os.path.basename(get('file_path', '?'))}"
    if tool_name == "Bash":
        cmd = get("command", "?")
        if len(cmd) > 80:
            cmd = cmd[:80] + "..."
        return f"Bash: {cmd}"
    if tool_name in ("Grep", "Glob"):
        return f"{tool_name}: {get('pattern', '?')[:40]}"

    # MCP 도구: 주요 파라미터 표시
    if tool_name.startswith("mcp__"):
        # mcp__server__method -> server.method
        parts = tool_name.split("__")
        short = ".".join(parts[1:]) if len(parts) >= 3 else tool_name
        # ai-chat은 질문을 더 길게 표시
        max_len = 300 if "ai-chat" in tool_name or "ai_chat" in tool_name else 80
        if isinstance(tool_input, dict) and tool_input:
            # 첫 번째 string 파라미터 값 표시 (message, text, query 등)
            param_str = ""
            for k, v in tool_input.items():
                if isinstance(v, str) and v.strip():
                    val = v.strip()
                    if len(val) > max_len:
                        val = val[:max_len] + "..."
                    param_str = f": {val}"
                    break
            return f"{short}{param_str}"
        return short

    return tool_name


def summarize_ai_chat_response(tool_name, tool_response):
    """ai-chat 도구 응답을 요약하여 반환. ai-chat이 아니면 None."""
    if not (tool_name.startswith("mcp__ai-chat") or tool_name.startswith("mcp__ai_chat")):
        return None
    if not tool_response:
        return None
    # tool_response가 JSON 문자열일 수 있음
    resp = tool_response
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except (json.JSONDecodeError, ValueError):
            # 순수 문자열 응답
            text = resp.strip()
            if len(text) < 5:
                return None
            if len(text) > 800:
                text = text[:800] + "..."
            return text
    if isinstance(resp, dict):
        text = ""
        for key in ("result", "content", "text", "answer", "response"):
            val = resp.get(key)
            if isinstance(val, str) and val.strip():
                text = val.strip()
                break
        if not text:
            text = str(resp)
        if len(text) < 5:
            return None
        # 에러 응답은 그대로 표시
        if len(text) > 800:
            text = text[:800] + "..."
        return text
    return None

def get_last_assistant_text(transcript_path):
    """transcript jsonl 끝부분에서 마지막 assistant 텍스트 추출"""
    if not transcript_path or not os.path.exists(transcript_path):
        return None
    try:
        with open(transcript_path, "rb") as f:
            # 끝에서 20KB만 읽기
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 20480))
            tail = f.read().decode("utf-8", errors="ignore")

        last_text = None
        for line in tail.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            content = entry.get("message", {}).get("content", [])
            for block in content:
                if block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        last_text = text
        return last_text
    except Exception:
        return None

def load_last_sent(session_id):
    """이전에 전송한 텍스트 로드"""
    path = f"{STATE_DIR}/.relay_lasttxt_{session_id[:8]}"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return ""

def save_last_sent(session_id, text):
    path = f"{STATE_DIR}/.relay_lasttxt_{session_id[:8]}"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass

def main():
    config = get_config()
    if not config:
        return

    bot_token, chat_id, bot_name = config
    bot_id = bot_token.split(":")[0]

    if not is_relay_enabled(bot_id, chat_id):
        return

    hook_data = sys.stdin.buffer.read().decode("utf-8", errors="replace")

    if not hook_data:
        return

    try:
        data = json.loads(hook_data)
    except json.JSONDecodeError:
        return

    session_id = data.get("session_id", "")
    tool_name = data.get("tool_name", "")

    if not is_supervised_session(session_id):
        return

    # 도구 요약을 생략할 도구들 (텍스트 중계는 함)
    SILENT_TOOLS = {"Read", "Grep", "Glob", "Agent"}
    is_telegram_tool = tool_name.startswith("mcp__telegram")
    is_silent = tool_name in SILENT_TOOLS or is_telegram_tool

    if is_silent:
        # send_message는 이미 텔레그램으로 보내므로 텍스트 중복 방지
        if "send_message" in tool_name:
            return
        transcript_path = data.get("transcript_path", "")
        if transcript_path:
            assistant_text = get_last_assistant_text(transcript_path)
            if assistant_text:
                prev = load_last_sent(session_id)
                if assistant_text != prev:
                    save_last_sent(session_id, assistant_text)
                    if len(assistant_text) > 300:
                        assistant_text = assistant_text[:300] + "..."
                    text = f"[{bot_name}] {assistant_text}"
                    send_telegram(bot_token, chat_id, text)
        return

    try:
        messages = []

        # 1. Claude 중간 텍스트 (transcript에서 추출)
        transcript_path = data.get("transcript_path", "")
        if transcript_path:
            assistant_text = get_last_assistant_text(transcript_path)
            if assistant_text:
                prev = load_last_sent(session_id)
                if assistant_text != prev:
                    save_last_sent(session_id, assistant_text)
                    if len(assistant_text) > 300:
                        assistant_text = assistant_text[:300] + "..."
                    messages.append(assistant_text)

        # 2. 도구 요약 (Edit, Write, Bash, MCP만)
        messages.append(summarize(tool_name, data.get("tool_input", {})))

        # 3. ai-chat 응답 내용 추가
        tool_response = data.get("tool_response")
        ai_resp = summarize_ai_chat_response(tool_name, tool_response or {})
        if ai_resp:
            messages.append(f"\n💬 AI 답변:\n{ai_resp}")

        text = f"[{bot_name}] " + "\n".join(messages)
        if len(text) > 4000:
            text = text[:4000] + "..."

        send_telegram(bot_token, chat_id, text)
    except Exception:
        pass

if __name__ == "__main__":
    main()

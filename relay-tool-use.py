#!/usr/bin/env python3
"""PostToolUse hook: 도구 사용 + Claude 중간 텍스트를 텔레그램으로 중계."""
import json
import os
import re
import sys

_SUPERVISOR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SUPERVISOR_DIR)
from relay_common import get_config, is_relay_enabled, is_supervised_session, send_telegram, send_telegram_photo, LOGS_DIR

STATE_DIR = LOGS_DIR

def summarize(tool_name, tool_input):
    """도구 사용을 한 줄로 요약하여 텔레그램 중계용 텍스트를 생성한다.

    Args:
        tool_name: Claude 도구명 (예: "Read", "Bash", "mcp__ai-chat__ask_ai")
        tool_input: 도구 입력 파라미터 dict (또는 비-dict 값)

    Returns:
        80자 이내 요약 문자열 (ai-chat 도구는 300자)
    """
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

def filter_assistant_text(text):
    """assistant 텍스트에서 노이즈를 제거하고 압축한다.

    - Shell cwd was reset 라인 제거
    - 연속된 OK/PASS 라인을 요약으로 압축 (FAIL은 유지)
    - 내부 도구 표시(─ 🔧) 라인 제거
    """
    lines = text.splitlines()
    filtered = []
    ok_count = 0
    fail_lines = []

    for line in lines:
        stripped = line.strip()
        # Shell cwd reset 노이즈 제거
        if stripped.startswith("Shell cwd was reset"):
            continue
        # 도구 내부 표시 제거
        if "─ 🔧" in stripped or "─ \U0001f527" in stripped:
            continue
        # 테스트 OK/PASS 라인 압축
        if re.match(r'^\s*(OK|✓|PASS|✅)\s+', stripped):
            ok_count += 1
            continue
        # FAIL 라인은 유지
        if re.match(r'^\s*(FAIL|✗|❌)\s+', stripped):
            fail_lines.append(stripped)
            continue
        # OK/FAIL 블록이 끝났으면 요약 삽입
        if ok_count > 0 or fail_lines:
            total = ok_count + len(fail_lines)
            summary = f"{ok_count}/{total} 통과"
            if fail_lines:
                summary += ", FAIL: " + "; ".join(fail_lines)
            filtered.append(summary)
            ok_count = 0
            fail_lines = []
        filtered.append(line)

    # 마지막 OK/FAIL 블록 처리
    if ok_count > 0 or fail_lines:
        total = ok_count + len(fail_lines)
        summary = f"{ok_count}/{total} 통과"
        if fail_lines:
            summary += ", FAIL: " + "; ".join(fail_lines)
        filtered.append(summary)

    return "\n".join(filtered).strip()


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

    # 스크린샷 도구: 이미지를 텔레그램으로 전송
    if tool_name in ("mcp__emulator-test__screenshot", "mcp__emulator-test__screenshot_raw"):
        tool_response = data.get("tool_response", "")
        if isinstance(tool_response, str):
            try:
                tool_response = json.loads(tool_response)
            except (json.JSONDecodeError, ValueError):
                pass
        result_text = tool_response.get("result", "") if isinstance(tool_response, dict) else str(tool_response)
        # "saved: /path/to/file.jpg (123KB)" 에서 경로 추출
        match = re.search(r"saved:\s*(.+?)\s*\(", result_text)
        if match:
            photo_path = match.group(1).strip()
            if os.path.exists(photo_path):
                send_telegram_photo(bot_token, chat_id, photo_path,
                    caption=f"[{bot_name}] 📸 {os.path.basename(photo_path)}")
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
                    assistant_text = filter_assistant_text(assistant_text)
                    if not assistant_text:
                        return
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
                    assistant_text = filter_assistant_text(assistant_text)
                    if assistant_text:
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
    except Exception as e:
        print(f"[relay-tool-use] main 처리 실패: {e}", file=sys.stderr, flush=True)

if __name__ == "__main__":
    main()

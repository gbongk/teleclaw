#!/usr/bin/env python3
"""
슈퍼바이저 래퍼 — supervisor.py를 감싸서 자동 재시작 + 데스루프 방지.

- 30초 미만 생존 = 코드 에러로 판정
- 지수 백오프: 3초 → 30초 → 5분 → 30분(최대)
- 텔레그램 알림: 비정상 종료 시 에러 로그 전송
- 백오프 대기 중 텔레그램 비상 명령어 수신
"""

import os
import sys
import time
import json
import subprocess
import urllib.request

# Windows cp949 인코딩 문제 방지
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SUPERVISOR = os.path.join(os.path.dirname(__file__), "supervisor.py")
PYTHON = sys.executable
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOGS_DIR, "wrapper.log")
SV_LOG_FILE = os.path.join(LOGS_DIR, "supervisor.log")
LOCK_FILE = os.path.join(LOGS_DIR, "wrapper.lock")
CHAT_ID = "8510879138"
BOT_TOKEN = "8590076448:AAHea0Rwj568h5-qcT4aqhSwsf2maGKA-2Y"

MIN_ALIVE_SEC = 30
BACKOFF_BASE = 3
BACKOFF_MAX = 1800  # 30분
EXIT_ALREADY_RUNNING = 42


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > 200:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines[-200:])
    except Exception:
        pass


def tg_send(text: str):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = json.dumps({
            "chat_id": CHAT_ID,
            "text": text[:4096],
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        log(f"텔레그램 알림 실패: {e}")


def tg_get_updates(offset: int, timeout: int = 5) -> tuple[list, int]:
    """텔레그램 메시지 폴링. (messages, new_offset) 반환."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        data = json.dumps({
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": ["message"],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=timeout + 10)
        result = json.loads(resp.read()).get("result", [])
        messages = []
        new_offset = offset
        for u in result:
            new_offset = u["update_id"] + 1
            msg = u.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if chat_id != CHAT_ID:
                continue
            text = msg.get("text", "")
            if text:
                messages.append(text)
        return messages, new_offset
    except Exception:
        return [], offset


def tg_flush(offset: int) -> int:
    """기존 pending 메시지를 모두 소비하고 최신 offset 반환."""
    msgs, new_offset = tg_get_updates(offset, timeout=0)
    while msgs:
        msgs, new_offset = tg_get_updates(new_offset, timeout=0)
    return new_offset


def handle_emergency_command(text: str, fail_count: int, wait: int, start_time: float) -> str | None:
    """비상 명령어 처리. 반환값: 'restart' = 즉시 재시작, 'kill' = 래퍼 종료, None = 계속 대기."""
    cmd = text.strip().lower()

    if cmd in ("/log", "/logs", "로그"):
        lines = []
        for path, label in [(LOG_FILE, "wrapper"), (SV_LOG_FILE, "supervisor")]:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    tail = f.readlines()[-10:]
                lines.append(f"📋 {label}:")
                lines.extend(l.rstrip() for l in tail)
            except Exception:
                lines.append(f"📋 {label}: 읽기 실패")
            lines.append("")
        tg_send("\n".join(lines))
        return None

    if cmd in ("/status", "상태"):
        uptime = int(time.time() - start_time)
        h, m = uptime // 3600, (uptime % 3600) // 60
        tg_send(
            f"🔧 래퍼 비상 모드\n"
            f"가동: {h}시간 {m}분\n"
            f"연속 실패: {fail_count}회\n"
            f"백오프: {wait}초\n"
            f"슈퍼바이저: 중지됨"
        )
        return None

    if cmd in ("/restart", "재시작", "/force"):
        tg_send("🔄 슈퍼바이저 즉시 재시작합니다.")
        return "restart"

    if cmd in ("/kill", "종료"):
        tg_send("🛑 래퍼를 종료합니다. 수동 시작이 필요합니다.")
        return "kill"

    if cmd in ("/help", "도움"):
        tg_send(
            "🔧 래퍼 비상 명령어\n"
            "  /log — 최근 로그 확인\n"
            "  /status — 현재 상태\n"
            "  /restart — 즉시 재시작\n"
            "  /kill — 래퍼 종료\n"
            "  /ask <메시지> — Claude에게 질문\n"
            "  /help — 이 목록"
        )
        return None

    # /ask — Claude CLI로 임시 질문
    if text.strip().lower().startswith("/ask "):
        question = text.strip()[5:].strip()
        if not question:
            tg_send("사용법: /ask <질문>")
            return None
        tg_send(f"🤖 Claude에게 질문 중...")
        try:
            r = subprocess.run(
                ["claude", "-p", question, "--output-format", "text"],
                capture_output=True, text=True, timeout=120,
                cwd=os.path.dirname(__file__),
            )
            answer = r.stdout.strip()
            if answer:
                # 4096자 제한
                if len(answer) > 3900:
                    answer = answer[:3900] + "\n... (잘림)"
                tg_send(f"🤖 Claude:\n{answer}")
            elif r.stderr.strip():
                tg_send(f"❌ Claude 에러:\n{r.stderr[:1000]}")
            else:
                tg_send("🤖 Claude: (빈 응답)")
        except subprocess.TimeoutExpired:
            tg_send("⏰ Claude 응답 시간 초과 (2분)")
        except Exception as e:
            tg_send(f"❌ Claude 실행 실패: {e}")
        return None

    return None


_poll_offset = 0  # 폴링 offset (모듈 레벨로 유지)

def wait_with_polling(wait_sec: int, fail_count: int, start_time: float) -> str | None:
    """백오프 대기 중 텔레그램 폴링. 'restart'/'kill' 반환 시 즉시 탈출."""
    global _poll_offset
    deadline = time.time() + wait_sec
    log(f"비상 폴링 시작 (대기 {wait_sec}초)")

    while time.time() < deadline:
        remaining = int(deadline - time.time())
        if remaining <= 0:
            break
        poll_timeout = min(remaining, 10)
        messages, _poll_offset = tg_get_updates(_poll_offset, timeout=poll_timeout)
        for text in messages:
            log(f"비상 명령 수신: {text}")
            result = handle_emergency_command(text, fail_count, wait_sec, start_time)
            if result:
                return result

    log("비상 폴링 종료")
    return None


def _is_pid_alive(pid: int) -> bool:
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        return str(pid) in r.stdout
    except Exception:
        return False


def _acquire_lock() -> bool:
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                data = json.load(f)
            old_pid = data.get("pid", 0)
            if _is_pid_alive(old_pid):
                return False
        except Exception:
            pass
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            json.dump({"pid": os.getpid(), "started": time.time()}, f)
        return True
    except (FileExistsError, OSError):
        return False


def _release_lock():
    try:
        os.remove(LOCK_FILE)
    except Exception:
        pass


def main():
    if not _acquire_lock():
        print("이미 래퍼가 실행 중입니다.")
        sys.exit(0)

    global _poll_offset
    fail_count = 0
    notified = False
    start_time = time.time()

    # 시작 시 기존 메시지 flush (1회만)
    _poll_offset = tg_flush(0)

    log("래퍼 시작")

    while True:
        log(f"supervisor 시작 (fail_count={fail_count})")
        sv_start = time.time()

        proc = subprocess.run(
            [PYTHON, SUPERVISOR],
            cwd=os.path.dirname(SUPERVISOR),
        )

        elapsed = time.time() - sv_start
        exit_code = proc.returncode
        log(f"supervisor 종료 (exit_code={exit_code}, 생존={elapsed:.0f}초)")

        # 기존 인스턴스 실행 중 → 60초 폴링 대기
        if exit_code == EXIT_ALREADY_RUNNING:
            log("기존 슈퍼바이저 실행 중, 60초 대기")
            result = wait_with_polling(60, fail_count, start_time)
            if result == "kill":
                return
            continue

        if elapsed >= MIN_ALIVE_SEC:
            fail_count = 0
            notified = False
            wait = BACKOFF_BASE
        else:
            fail_count += 1
            wait = min(BACKOFF_BASE * (2 ** (fail_count - 1)), BACKOFF_MAX)

            if not notified:
                tg_send(
                    f"⚠️ 슈퍼바이저 비정상 종료\n"
                    f"생존시간: {elapsed:.0f}초\n"
                    f"exit_code: {exit_code}\n"
                    f"연속 실패: {fail_count}회\n"
                    f"다음 재시도: {wait}초 후\n"
                    f"비상 명령: /help"
                )
                notified = True
                log("텔레그램 알림 전송")

            log(f"빠른 종료 감지 (연속 {fail_count}회), {wait}초 대기")

        # 대기 중 텔레그램 폴링 (비상 명령 수신)
        result = wait_with_polling(wait, fail_count, start_time)
        if result == "kill":
            return
        if result == "restart":
            fail_count = 0
            notified = False


if __name__ == "__main__":
    try:
        main()
    finally:
        _release_lock()

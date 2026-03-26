"""슈퍼바이저 명령어 핸들러"""

import asyncio
import json
import time
from pathlib import Path

from .config import (
    SUPERVISOR_DIR, LOGS_DIR, LOG_FILE, TELEGRAM_DIR,
)
from .logging_utils import log
from .telegram_api import send_telegram


async def _do_interrupt(state, name: str, bot_token: str):
    """세션의 현재 작업을 중단한다."""
    try:
        await state.client.interrupt()
        log(f"{name}: interrupt 완료")
        send_telegram(f"[SV] {name}: 작업 중단됨", bot_token)
    except Exception as e:
        log(f"{name}: interrupt 실패: {e}")
        send_telegram(f"[SV] {name}: interrupt 실패 ({e})", bot_token)


def _find_session_by_token(sessions: dict, bot_token: str) -> str | None:
    """bot_token에 해당하는 세션 이름을 반환한다. 없으면 None."""
    for name, state in sessions.items():
        if state.config["bot_token"] == bot_token:
            return name
    return None


def _get_usage(http_client) -> str:
    """Anthropic OAuth Usage API로 토큰 사용량 조회 (60초 캐시).

    /usage 명령 수신 시 호출. http_client는 httpx.Client 인스턴스.
    """
    import os
    cache_path = Path(os.environ.get("TEMP", "/tmp")) / "claude-sv-usage.json"
    # 캐시 확인
    try:
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - cached.get("_ts", 0) < 60:
                return cached["_text"]
    except Exception:
        pass

    # OAuth 토큰 읽기
    cred_path = Path.home() / ".claude" / ".credentials.json"
    try:
        creds = json.loads(cred_path.read_text(encoding="utf-8"))
        token = creds["claudeAiOauth"]["accessToken"]
    except Exception as e:
        return f"[SV] 사용량 조회 실패: credentials 읽기 에러 ({e})"

    # API 호출
    try:
        r = http_client.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return f"[SV] 사용량 조회 실패: HTTP {r.status_code}"
        data = r.json()
    except Exception as e:
        return f"[SV] 사용량 조회 실패: {e}"

    from .usage_fmt import usage_bar as _bar, reset_str as _reset_str

    five = data.get("five_hour", {})
    seven = data.get("seven_day", {})
    sonnet = data.get("seven_day_sonnet", {})
    opus = data.get("seven_day_opus", {})

    lines = ["[SV] Claude 사용량"]
    lines.append("")

    if five.get("utilization") is not None:
        pct = five["utilization"]
        lines.append(f"5h   {_bar(pct)} {_reset_str(five)}")
    if seven.get("utilization") is not None:
        pct = seven["utilization"]
        lines.append(f"7d   {_bar(pct)} {_reset_str(seven)}")
    if sonnet and sonnet.get("utilization") is not None:
        pct = sonnet["utilization"]
        lines.append(f"Son  {_bar(pct)} {_reset_str(sonnet)}")
    if opus and opus.get("utilization") is not None:
        pct = opus["utilization"]
        lines.append(f"Opus {_bar(pct)} {_reset_str(opus)}")

    text = "\n".join(lines)
    # 캐시 저장
    try:
        cache_path.write_text(json.dumps({"_ts": time.time(), "_text": text}), encoding="utf-8")
    except Exception:
        pass
    return text


def handle_command(supervisor, text: str, bot_token: str) -> bool:
    """텔레그램 메시지가 /로 시작할 때 호출. 처리했으면 True 반환.

    지원 명령: /status, /esc, /pause, /restart, /reset, /log, /usage, /sys, /ask, /help
    """
    text = text.strip()
    if not text.startswith("/"):
        return False

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/stop", "/shutdown", "/kill"):
        send_telegram("[SV] 슈퍼바이저 종료는 채팅방에서 불가합니다.", bot_token)
        return True

    if cmd in ("/status", "/s"):
        now = time.time()
        uptime = int(now - supervisor._start_time)
        h, m = uptime // 3600, (uptime % 3600) // 60
        lines = [f"[SV] 가동 {h}시간 {m}분"]
        for name, state in supervisor.sessions.items():
            status = supervisor._assess_health(state)
            lines.append(
                f"  {name}: {status} | Q={state.query_count} E={state.error_count} R={state.restart_count}"
            )
        send_telegram("\n".join(lines), bot_token)
        return True

    if cmd in ("/restart", "/r"):
        no_resume = False
        if arg:
            parts = arg.split()
            name = parts[0]
            no_resume = "noresume" in parts[1:]
        else:
            name = _find_session_by_token(supervisor.sessions, bot_token)
        if name and name.lower() == "supervisor":
            send_telegram("[SV] 슈퍼바이저 재시작합니다...", bot_token)
            Path(TELEGRAM_DIR).joinpath("restart_request_supervisor.flag").write_text("force")
            return True
        if name and name in supervisor.sessions:
            # pause 상태라면 해제
            pause_flag = Path(TELEGRAM_DIR) / f"pause_{name}.flag"
            if pause_flag.exists():
                pause_flag.unlink(missing_ok=True)
                log(f"{name}: pause 해제됨 (/restart 명령)")
            asyncio.create_task(supervisor._restart_session(supervisor.sessions[name], "/restart 명령", mode="resume", force=True, no_resume=no_resume))
            tag = " (noresume)" if no_resume else ""
            send_telegram(f"[SV] {name} 재시작 요청됨{tag}", bot_token)
        elif name:
            send_telegram(f"[SV] 세션 '{name}' 없음. 가능: {', '.join(supervisor.sessions)}, supervisor", bot_token)
        return True


    if cmd in ("/pause", "/p"):
        if arg:
            name = arg
        else:
            name = _find_session_by_token(supervisor.sessions, bot_token)
        if name and name in supervisor.sessions:
            pause_flag = Path(TELEGRAM_DIR) / f"pause_{name}.flag"
            if pause_flag.exists():
                send_telegram(f"[SV] {name} 이미 일시정지 상태입니다", bot_token)
                return True
            pause_flag.write_text(str(int(time.time())))
            # 세션 disconnect
            state = supervisor.sessions[name]
            old_client = state.client
            state.client = None
            if old_client:
                asyncio.create_task(supervisor._safe_disconnect(old_client, name))
            state.connected = False
            state.busy = False
            log(f"{name}: 일시정지됨 (/pause 명령)")
            send_telegram(f"[SV] {name} 일시정지됨", bot_token)
        elif name:
            send_telegram(f"[SV] 세션 '{name}' 없음. 가능: {', '.join(supervisor.sessions)}", bot_token)
        return True

    if cmd in ("/esc", "/interrupt"):
        if arg:
            name = arg
        else:
            name = _find_session_by_token(supervisor.sessions, bot_token)
        if name and name in supervisor.sessions:
            state = supervisor.sessions[name]
            if state.connected and state.client:
                asyncio.create_task(_do_interrupt(state, name, bot_token))
            else:
                send_telegram(f"[SV] {name}: 연결 안 됨", bot_token)
        elif name:
            send_telegram(f"[SV] 세션 '{name}' 없음. 가능: {', '.join(supervisor.sessions)}", bot_token)
        return True

    if cmd == "/reset":
        if arg:
            name = arg
        else:
            name = _find_session_by_token(supervisor.sessions, bot_token)
        if name and name in supervisor.sessions:
            # pause 상태라면 해제
            pause_flag = Path(TELEGRAM_DIR) / f"pause_{name}.flag"
            if pause_flag.exists():
                pause_flag.unlink(missing_ok=True)
                log(f"{name}: pause 해제됨 (/reset 명령)")
            asyncio.create_task(supervisor._restart_session(supervisor.sessions[name], "/reset 명령 (컨텍스트 초기화)", mode="reset", force=True))
            send_telegram(f"[SV] {name} 리셋 요청됨", bot_token)
        elif name:
            send_telegram(f"[SV] 세션 '{name}' 없음. 가능: {', '.join(supervisor.sessions)}", bot_token)
        return True

    if cmd in ("/log", "/l"):
        n = int(arg) if arg and arg.isdigit() else 20
        n = min(n, 50)  # 텔레그램 메시지 길이 제한
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            tail = lines[-n:] if len(lines) >= n else lines
            text = f"[SV] 최근 로그 ({len(tail)}줄)\n\n" + "".join(tail)
            if len(text) > 4000:
                text = text[-4000:]
            send_telegram(text, bot_token)
        except Exception as e:
            send_telegram(f"[SV] 로그 읽기 실패: {e}", bot_token)
        return True

    if cmd in ("/usage", "/u"):
        usage_text = _get_usage(supervisor._http)
        send_telegram(usage_text, bot_token)
        return True

    if cmd == "/ctx":
        # 각 세션의 마지막 usage 로그에서 컨텍스트 사용량 추정
        lines = ["[SV] 컨텍스트 사용량 (추정)"]
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                log_lines = f.readlines()
        except Exception:
            log_lines = []
        for name, state in supervisor.sessions.items():
            usage_data = None
            for line in reversed(log_lines):
                if f"{name}: [usage]" in line:
                    try:
                        idx = line.index("{")
                        usage_data = eval(line[idx:].strip())
                    except Exception:
                        pass
                    break
            if usage_data:
                inp = usage_data.get("input_tokens", 0)
                cache_read = usage_data.get("cache_read_input_tokens", 0)
                cache_create = usage_data.get("cache_creation_input_tokens", 0)
                out = usage_data.get("output_tokens", 0)
                lines.append(
                    f"  {name}: in={inp:,} cache_r={cache_read:,} cache_w={cache_create:,} out={out:,}"
                )
            else:
                lines.append(f"  {name}: 데이터 없음")
        lines.append("\n⚠️ SDK usage 기반 추정값. 정확한 ctx%는 CLI 상태줄 참조")
        send_telegram("\n".join(lines), bot_token)
        return True

    if cmd == "/sys":
        proc_limit = int(arg) if arg and arg.isdigit() else 10
        proc_limit = min(proc_limit, 30)
        lines = ["[SV] 시스템 상태"]
        try:
            import psutil
            # CPU
            cpu_percent = psutil.cpu_percent(interval=0.5)
            cpu_count = psutil.cpu_count()
            lines.append(f"\n\U0001f5a5 CPU: {cpu_percent}% ({cpu_count}코어)")
            # Memory
            mem = psutil.virtual_memory()
            used_gb = mem.used / (1024**3)
            total_gb = mem.total / (1024**3)
            lines.append(f"\U0001f4be 메모리: {used_gb:.1f}/{total_gb:.1f}GB ({mem.percent}%)")
            # Disk
            disk = psutil.disk_usage("D:/")
            disk_used = disk.used / (1024**3)
            disk_total = disk.total / (1024**3)
            lines.append(f"\U0001f4c1 디스크(D:): {disk_used:.0f}/{disk_total:.0f}GB ({disk.percent}%)")
            # Claude processes
            lines.append(f"\n\U0001f4cb 프로세스 (상위 {proc_limit}개):")
            claude_procs = []
            for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent", "cmdline"]):
                try:
                    pname = proc.info["name"] or ""
                    cmdline = " ".join(proc.info["cmdline"] or [])
                    mem_mb = (proc.info["memory_info"].rss / (1024**2)) if proc.info["memory_info"] else 0
                    if "claude" in pname.lower():
                        claude_procs.append((pname, proc.info["pid"], mem_mb, proc.info["cpu_percent"] or 0))
                    elif "node" in pname.lower() and "mcp" in cmdline.lower():
                        claude_procs.append((pname, proc.info["pid"], mem_mb, proc.info["cpu_percent"] or 0))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if claude_procs:
                for pname, pid, mem_mb, cpu_p in sorted(claude_procs, key=lambda x: -x[2])[:proc_limit]:
                    lines.append(f"  {pname}(PID:{pid}) {mem_mb:.0f}MB CPU:{cpu_p:.0f}%")
            else:
                lines.append("  Claude 관련 프로세스 없음")
            # Supervisor self
            sv_proc = psutil.Process()
            sv_mem = sv_proc.memory_info().rss / (1024**2)
            lines.append(f"\n\U0001f916 슈퍼바이저: PID:{sv_proc.pid} {sv_mem:.0f}MB")
        except ImportError:
            lines.append("psutil 미설치. pip install psutil")
        except Exception as e:
            lines.append(f"오류: {e}")
        send_telegram("\n".join(lines), bot_token)
        return True

    if cmd == "/ask":
        if not arg:
            send_telegram("[SV] 사용법: /ask <질문>", bot_token)
            return True
        asyncio.create_task(supervisor._handle_ask(arg, bot_token))
        return True

    if cmd in ("/help", "/h"):
        names = ", ".join(supervisor.sessions.keys())
        send_telegram(
            "[SV] 명령어\n"
            f"\n"
            f"\U0001f4ca 상태\n"
            f"  /status (/s) \u2014 세션 상태\n"
            f"  /usage  (/u) \u2014 사용량\n"
            f"  /ctx \u2014 컨텍스트 사용량\n"
            f"  /sys \u2014 시스템\n"
            f"  /log (/l) [N] \u2014 로그\n"
            f"\n"
            f"\U0001f504 세션\n"
            f"  /esc <name> \u2014 작업 중단 (interrupt)\n"
            f"  /pause (/p) <name> \u2014 일시정지\n"
            f"  /restart (/r) <name> [noresume] \u2014 재시작\n"
            f"  /reset <name> \u2014 리셋\n"
            f"\n"
            f"\u2139\ufe0f 기타\n"
            f"  /ask <질문> \u2014 Claude 질문\n"
            f"  /help (/h) \u2014 이 목록\n"
            f"\n"
            f"세션: {names}",
            bot_token,
        )
        return True

    return False

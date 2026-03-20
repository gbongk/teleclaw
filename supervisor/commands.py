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


def _find_session_by_token(sessions: dict, bot_token: str) -> str | None:
    for name, state in sessions.items():
        if state.config["bot_token"] == bot_token:
            return name
    return None


def _get_usage(http_client) -> str:
    """Anthropic OAuth Usage API로 토큰 사용량 조회 (60초 캐시)"""
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

    # 포맷
    def _bar(pct):
        filled = round(pct / 5)  # 20칸 바
        empty = 20 - filled
        if pct >= 90:
            icon = "\U0001f534"
        elif pct >= 70:
            icon = "\U0001f7e1"
        else:
            icon = "\U0001f7e2"
        return f"{icon} {'|' * filled}{'.' * empty} {pct:.0f}%"

    from datetime import datetime, timezone

    def _reset_str(bucket):
        reset_at = bucket.get("resets_at", "") if bucket else ""
        if not reset_at:
            return ""
        try:
            dt = datetime.fromisoformat(reset_at)
            remaining = (dt - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                return "(\ub9ac\uc14b\ub428)"
            rm, rs = divmod(int(remaining), 60)
            rh, rm = divmod(rm, 60)
            if rh > 0:
                return f"({rh}h {rm}m)"
            return f"({rm}m)"
        except Exception:
            return ""

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
    """슈퍼바이저 명령어 처리. 처리했으면 True 반환."""
    text = text.strip()
    if not text.startswith("/"):
        return False

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/stop", "/shutdown", "/kill"):
        send_telegram("[SV] 슈퍼바이저 종료는 채팅방에서 불가합니다.", bot_token)
        return True

    if cmd == "/status":
        now = time.time()
        uptime = int(now - supervisor._start_time)
        h, m = uptime // 3600, (uptime % 3600) // 60
        lines = [f"[SV] 가동 {h}시간 {m}분"]
        for name, state in supervisor.sessions.items():
            status = "PAUSED" if state.paused else supervisor._assess_health(state)
            lines.append(
                f"  {name}: {status} | Q={state.query_count} E={state.error_count} R={state.restart_count}"
            )
        send_telegram("\n".join(lines), bot_token)
        return True

    if cmd == "/restart":
        if arg:
            name = arg
        else:
            name = _find_session_by_token(supervisor.sessions, bot_token)
        if name and name.lower() == "supervisor":
            send_telegram("[SV] 슈퍼바이저 재시작합니다...", bot_token)
            Path(TELEGRAM_DIR).joinpath("restart_request_supervisor.flag").write_text("resume")
            return True
        if name and name in supervisor.sessions:
            asyncio.create_task(supervisor._restart_session(supervisor.sessions[name], "/restart 명령", mode="resume"))
            send_telegram(f"[SV] {name} 재시작 요청됨", bot_token)
        elif name:
            send_telegram(f"[SV] 세션 '{name}' 없음. 가능: {', '.join(supervisor.sessions)}, supervisor", bot_token)
        return True

    if cmd == "/wakeup":
        # /wakeup → 봇 ID로 프로젝트 매핑, /wakeup <name> → 이름으로 매핑
        if arg:
            target = arg
        else:
            # 봇 토큰으로 프로젝트 찾기
            target = None
            for sname, sstate in supervisor.sessions.items():
                if sstate.config["bot_token"] == bot_token:
                    target = sname
                    break
        if target and target in supervisor.sessions:
            pause_path = Path(TELEGRAM_DIR) / f"telegram_pause_{target}.flag"
            if pause_path.exists():
                pause_path.unlink(missing_ok=True)
                send_telegram(f"[SV] {target}: wakeup 요청됨, pause 해제 중...", bot_token)
            else:
                send_telegram(f"[SV] {target}: 일시정지 상태가 아닙니다", bot_token)
        elif target:
            send_telegram(f"[SV] 세션 '{target}' 없음. 가능: {', '.join(supervisor.sessions)}", bot_token)
        return True

    if cmd == "/pause" and arg:
        name = arg
        if name in supervisor.sessions:
            pause_path = Path(TELEGRAM_DIR) / f"telegram_pause_{name}.flag"
            if pause_path.exists():
                send_telegram(f"[SV] {name}: 이미 일시정지 상태입니다", bot_token)
            else:
                pause_path.write_text("pause")
                send_telegram(f"[SV] {name}: 일시정지 요청됨", bot_token)
        else:
            send_telegram(f"[SV] 세션 '{name}' 없음. 가능: {', '.join(supervisor.sessions)}", bot_token)
        return True

    if cmd == "/reset":
        if arg:
            name = arg
        else:
            name = _find_session_by_token(supervisor.sessions, bot_token)
        if name and name in supervisor.sessions:
            asyncio.create_task(supervisor._restart_session(supervisor.sessions[name], "/reset 명령 (컨텍스트 초기화)", mode="reset"))
            send_telegram(f"[SV] {name} 리셋 요청됨", bot_token)
        elif name:
            send_telegram(f"[SV] 세션 '{name}' 없음. 가능: {', '.join(supervisor.sessions)}", bot_token)
        return True

    if cmd == "/log":
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

    if cmd == "/usage":
        usage_text = _get_usage(supervisor._http)
        send_telegram(usage_text, bot_token)
        return True

    if cmd == "/sys":
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
            lines.append(f"\n\U0001f4cb 프로세스:")
            claude_procs = []
            node_procs = []
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
                for pname, pid, mem_mb, cpu_p in sorted(claude_procs, key=lambda x: -x[2]):
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

    if cmd == "/help":
        names = ", ".join(supervisor.sessions.keys())
        send_telegram(
            "[SV] 명령어 목록 (슈퍼바이저 정상 가동 중)\n"
            f"\n"
            f"\U0001f4ca 상태\n"
            f"  /status \u2014 전체 세션 상태 (가동시간, 쿼리수, 에러수)\n"
            f"  /usage \u2014 토큰 사용량 (rate limit 사용률)\n"
            f"  /sys \u2014 시스템 상태 (CPU, 메모리, 프로세스)\n"
            f"  /log [N] \u2014 최근 로그 N줄 (기본 20, 최대 50)\n"
            f"\n"
            f"\U0001f504 세션 관리\n"
            f"  /restart <name> \u2014 세션 재시작 (SDK reconnect, 컨텍스트 유지)\n"
            f"  /reset <name> \u2014 세션 리셋 (새 대화, 컨텍스트 초기화)\n"
            f"  /pause <name> \u2014 세션 일시정지 (메시지 수신 중단)\n"
            f"  /wakeup [name] \u2014 pause 해제 (이름 생략 시 현재 채팅방)\n"
            f"\n"
            f"\u2139\ufe0f 기타\n"
            f"  /ask <질문> \u2014 Claude에게 질문 (상시 세션)\n"
            f"  /help \u2014 이 목록\n"
            f"\n"
            f"세션: {names}",
            bot_token,
        )
        return True

    return False

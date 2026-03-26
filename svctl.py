#!/usr/bin/env python3
"""슈퍼바이저 CLI — 텔레그램/콘솔 양쪽에서 사용 가능한 명령어 도구.

사용법:
  python sv.py s              # 상태
  python sv.py r [name]       # 재시작 (기본: 현재 프로젝트)
  python sv.py x [name]       # 리셋 (컨텍스트 초기화)
  python sv.py p <name>       # 일시정지
  python sv.py w [name]       # 해제
  python sv.py l [N]          # 로그 (기본 20줄)
  python sv.py u              # 사용량
  python sv.py h              # 도움말
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SUPERVISOR_DIR = Path(__file__).resolve().parent
DATA_DIR = SUPERVISOR_DIR / "data"
LOGS_DIR = SUPERVISOR_DIR / "logs"
STATUS_FILE = LOGS_DIR / "hub_status.json"
LOG_FILE = LOGS_DIR / "supervisor.log"

# config.py에서 세션 목록 자동 로드 (단일 소스)
sys.path.insert(0, str(SUPERVISOR_DIR / "hub"))
try:
    from config import PROJECTS
    SESSION_NAMES = list(PROJECTS.keys())
    CWD_MAP = {}
    for name, info in PROJECTS.items():
        cwd = info["cwd"]
        CWD_MAP[cwd] = name
        CWD_MAP[cwd.replace("/", "\\")] = name
finally:
    sys.path.pop(0)


def _guess_session():
    cwd = os.getcwd().replace("\\", "/").rstrip("/")
    for path, name in CWD_MAP.items():
        if cwd.replace("\\", "/").rstrip("/") == path.replace("\\", "/").rstrip("/"):
            return name
    return None


def _resolve_name(arg):
    if not arg:
        name = _guess_session()
        if not name:
            print("세션 이름을 지정하세요:", ", ".join(SESSION_NAMES))
            return None
        return name
    # 대소문자 무시 매칭
    for n in SESSION_NAMES + ["supervisor"]:
        if n.lower() == arg.lower():
            return n
    print(f"세션 '{arg}' 없음. 가능: {', '.join(SESSION_NAMES)}, supervisor")
    return None


def _get_all_processes():
    """claude.exe + supervisor 관련 python 프로세스를 모두 조회한다.

    Returns:
        {"sessions": {name: {pid, mem_mb}},
         "manual": [{pid, mem_mb}],
         "infra": [{pid, mem_mb, label}]}
    """
    import re as _re
    # claude.exe + supervisor 관련 python 프로세스 조회
    ps_cmd = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq 'claude.exe' -or "
        "($_.Name -eq 'python.exe' -and $_.CommandLine -match 'supervisor') } | "
        "ForEach-Object { "
        "$mem = (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue).WorkingSet64; "
        "Write-Output ('{0}|{1}|{2}|{3}' -f $_.ProcessId, $_.Name, $mem, "
        "$_.CommandLine.Substring(0, [math]::Min(200, $_.CommandLine.Length))) }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-c", ps_cmd],
            capture_output=True, text=True, timeout=15
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    except Exception:
        return {"sessions": {}, "manual": [], "infra": []}

    # session_ids.json에서 세션 ID → 이름 매핑
    sid_to_name = {}
    if SESSION_IDS_FILE.exists():
        try:
            ids = json.loads(SESSION_IDS_FILE.read_text(encoding="utf-8"))
            for name, info in ids.items():
                sid = info.get("session_id", "")
                if sid:
                    sid_to_name[sid] = name
        except Exception:
            pass

    sessions = {}
    manual = []
    infra = []

    for line in lines:
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        pid = int(parts[0])
        proc_name = parts[1]
        mem_mb = round(int(parts[2] or 0) / 1024 / 1024)
        cmdline = parts[3]

        # python supervisor 프로세스
        if proc_name == "python.exe":
            if "supervisor-wrapper" in cmdline:
                infra.append({"pid": pid, "mem_mb": mem_mb, "label": "wrapper"})
            elif "supervisor" in cmdline:
                infra.append({"pid": pid, "mem_mb": mem_mb, "label": "supervisor"})
            continue

        # claude.exe — 세션 매핑
        matched_name = None
        if "--resume" in cmdline:
            for sid, sname in sid_to_name.items():
                if sid in cmdline:
                    matched_name = sname
                    break
        if not matched_name and "TELEGRAM_BOT_NAME" in cmdline:
            m = _re.search(r'TELEGRAM_BOT_NAME[\\"]* *[,:] *[\\"]*([\w]+)', cmdline)
            if m:
                matched_name = m.group(1)

        entry = {"pid": pid, "mem_mb": mem_mb}
        if matched_name:
            sessions[matched_name] = entry
        else:
            manual.append(entry)

    return {"sessions": sessions, "manual": manual, "infra": infra}


def cmd_sys():
    """시스템 CPU, 메모리 상태."""
    try:
        result = subprocess.run(
            ["powershell", "-c", (
                "$cpu = (Get-CimInstance Win32_Processor).LoadPercentage;"
                "$os = Get-CimInstance Win32_OperatingSystem;"
                "$totalGB = [math]::Round($os.TotalVisibleMemorySize/1MB, 1);"
                "$usedGB = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory)/1MB, 1);"
                "$pct = [math]::Round($usedGB/$totalGB*100);"
                "Write-Output \"$cpu|$usedGB|$totalGB|$pct\""
            )],
            capture_output=True, text=True, timeout=10
        )
        parts = result.stdout.strip().split("|")
        if len(parts) == 4:
            cpu, used, total, mem_pct = parts
            print(f"CPU: {cpu}%")
            print(f"RAM: {used}/{total}GB ({mem_pct}%)")
        else:
            print("시스템 정보 조회 실패")
    except Exception as e:
        print(f"오류: {e}")


def cmd_ps():
    """관련 프로세스 목록 및 상태."""
    all_procs = _get_all_processes()
    hub_data = {}

    # 슈퍼바이저 상태
    if STATUS_FILE.exists():
        hub_data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        ts = hub_data.get("ts", 0)
        saved_uptime = hub_data.get("uptime", 0)
        if ts and saved_uptime:
            uptime = int(saved_uptime + (time.time() - ts))
        else:
            uptime = 0
        h, m = uptime // 3600, (uptime % 3600) // 60
        sv_pid = hub_data.get("pid", "?")
        print(f"슈퍼바이저 PID={sv_pid} 가동: {h}시간 {m}분")
    else:
        print("슈퍼바이저 미실행")

    # 인프라 프로세스 (래퍼, supervisor python)
    for p in all_procs["infra"]:
        print(f"  {p['label']}: PID={p['pid']} {p['mem_mb']}MB")

    total_mb = sum(p["mem_mb"] for p in all_procs["infra"])

    # 세션 프로세스
    for name, sess in hub_data.get("sessions", {}).items():
        status = sess.get("status", "?")
        pause_flag = DATA_DIR / f"pause_{name}.flag"
        if pause_flag.exists():
            status = "PAUSED"
        q = sess.get("query_count", 0)
        e = sess.get("error_count", 0)
        r = sess.get("restart_count", 0)
        pi = all_procs["sessions"].get(name, {})
        pid_str = f"PID={pi['pid']}" if pi.get("pid") else "PID=?"
        mem_mb = pi.get("mem_mb", 0)
        mem_str = f"{mem_mb}MB" if mem_mb else "?MB"
        total_mb += mem_mb
        print(f"  {name}: {status} | {pid_str} {mem_str} | Q={q} E={e} R={r}")

    # 수동/미매핑 세션
    for i, p in enumerate(all_procs["manual"]):
        total_mb += p["mem_mb"]
        label = f"수동{i+1}" if len(all_procs["manual"]) > 1 else "수동"
        print(f"  ({label}): PID={p['pid']} {p['mem_mb']}MB")

    print(f"  합계: {total_mb}MB")


def cmd_restart(arg, mode="resume"):
    name = _resolve_name(arg)
    if not name:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if name.lower() == "supervisor":
        flag = DATA_DIR / "restart_request_supervisor.flag"
        flag.write_text("force")
        print("슈퍼바이저 재시작 요청됨")
    else:
        flag = DATA_DIR / f"restart_request_{name}.flag"
        parts = ["force"]
        if mode != "resume":
            parts.append(mode)
        flag.write_text(",".join(parts))
        mode_str = f" ({mode})" if mode != "resume" else ""
        print(f"{name} 재시작 요청됨{mode_str}")



def cmd_pause(arg):
    """세션을 일시정지 — 프로세스 종료 + 슈퍼바이저가 재시작하지 않음."""
    name = _resolve_name(arg)
    if not name or name.lower() == "supervisor":
        print("세션 이름을 지정하세요 (supervisor 불가)")
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    flag = DATA_DIR / f"pause_{name}.flag"
    flag.write_text(str(int(time.time())))
    # 프로세스 종료
    all_procs = _get_all_processes()
    pi = all_procs["sessions"].get(name)
    if pi and pi.get("pid"):
        try:
            subprocess.run(["taskkill", "//F", "//PID", str(pi["pid"])],
                           capture_output=True, timeout=10)
            print(f"{name} 일시정지됨 (PID={pi['pid']} 종료)")
        except Exception:
            print(f"{name} 일시정지 플래그 생성됨 (프로세스 종료 실패)")
    else:
        print(f"{name} 일시정지됨 (프로세스 없음)")


def cmd_log(arg):
    n = int(arg) if arg and arg.isdigit() else 20
    n = min(n, 50)
    if not LOG_FILE.exists():
        print("로그 파일 없음")
        return
    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    for line in lines[-n:]:
        print(line)


def cmd_usage():
    cred_path = Path.home() / ".claude" / ".credentials.json"
    try:
        creds = json.loads(cred_path.read_text(encoding="utf-8"))
        token = creds["claudeAiOauth"]["accessToken"]
    except Exception as e:
        print(f"credentials 읽기 실패: {e}")
        return
    try:
        import httpx
        r = httpx.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
            timeout=10,
        )
        if r.status_code != 200:
            print(f"사용량 조회 실패: HTTP {r.status_code}")
            return
        data = r.json()
    except Exception as e:
        print(f"사용량 조회 실패: {e}")
        return

    from datetime import datetime, timezone

    sys.path.insert(0, str(SUPERVISOR_DIR / "hub"))
    from usage_fmt import usage_bar as _bar, reset_str as _reset_str

    five = data.get("five_hour", {})
    seven = data.get("seven_day", {})
    if five.get("utilization") is not None:
        print(f"5h   {_bar(five['utilization'])} {_reset_str(five)}")
    if seven.get("utilization") is not None:
        print(f"7d   {_bar(seven['utilization'])} {_reset_str(seven)}")


# config.py의 cwd에서 자동 생성 (D:/workspace/foo → D--workspace-foo)
PROJECT_DIRS = {
    name: info["cwd"].replace(":", "").replace("/", "-").replace("\\", "-")
    for name, info in PROJECTS.items()
}
SESSIONS_BASE = Path.home() / ".claude" / "projects"
SESSION_IDS_FILE = LOGS_DIR / "session_ids.json"


def cmd_ctx():
    if not SESSION_IDS_FILE.exists():
        print("session_ids.json 없음")
        return
    ids = json.loads(SESSION_IDS_FILE.read_text(encoding="utf-8"))
    for name in SESSION_NAMES:
        info = ids.get(name)
        if not info:
            print(f"  {name}: 세션 없음")
            continue
        sid = info.get("session_id", "")
        proj_dir = PROJECT_DIRS.get(name)
        if not proj_dir or not sid:
            print(f"  {name}: 매핑 없음")
            continue
        jsonl = SESSIONS_BASE / proj_dir / f"{sid}.jsonl"
        if not jsonl.exists():
            print(f"  {name}: transcript 없음")
            continue
        try:
            with open(jsonl, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 100000))
                tail = f.read().decode("utf-8", errors="ignore")
            last_usage = None
            last_model = ""
            for line in tail.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if entry.get("type") == "assistant":
                    msg = entry.get("message", {})
                    u = msg.get("usage")
                    if u:
                        last_usage = u
                    m = msg.get("model", "")
                    if m:
                        last_model = m
            if not last_usage:
                print(f"  {name}: usage 데이터 없음")
                continue
            inp = last_usage.get("input_tokens", 0)
            cache_create = last_usage.get("cache_creation_input_tokens", 0)
            cache_read = last_usage.get("cache_read_input_tokens", 0)
            total = inp + cache_create + cache_read
            # 모델별 컨텍스트 크기
            if "1m" in last_model or "opus" in last_model:
                ctx_size = 1000000
            else:
                ctx_size = 200000
            pct = total / ctx_size * 100
            bar_filled = round(pct / 5)
            bar = "|" * bar_filled + "." * (20 - bar_filled)
            print(f"  {name}: {bar} {pct:.0f}% ({total:,}/{ctx_size:,})")
        except Exception as e:
            print(f"  {name}: 오류 - {e}")


def cmd_help():
    print("svctl — 슈퍼바이저 CLI")
    print()
    print("  sys             시스템 CPU/RAM")
    print("  ps              프로세스 목록")
    print("  c, ctx          컨텍스트 사용량")
    print("  u, usage        토큰 사용량")
    print("  r, restart [n]  세션 재시작")
    print("  (텔레그램 /esc <name> — 작업 중단, svctl 미지원)")
    print("  sv              슈퍼바이저 재시작")
    print("  reset [name]    리셋 (새 대화)")
    print("  p, pause [n]    세션 일시정지 (종료+재시작 방지, restart/reset으로 해제)")
    print("  l, log [N]      로그 (기본 20줄)")
    print("  h, help         도움말")
    print()
    print(f"세션: {', '.join(SESSION_NAMES)}, supervisor")
    print("name 생략 시 현재 디렉토리에서 추정")


def main():
    if len(sys.argv) < 2:
        cmd_help()
        return

    cmd = sys.argv[1].lower().lstrip("/")
    arg = sys.argv[2] if len(sys.argv) > 2 else ""

    commands = {
        "sys": cmd_sys, "system": cmd_sys,
        "ps": cmd_ps, "s": cmd_ps, "status": cmd_ps,
        "r": lambda: cmd_restart(arg), "restart": lambda: cmd_restart(arg),
        "sv": lambda: cmd_restart("supervisor"), "supervisor": lambda: cmd_restart("supervisor"),
        "reset": lambda: cmd_restart(arg, "reset"),
        "p": lambda: cmd_pause(arg), "pause": lambda: cmd_pause(arg),
        "c": cmd_ctx, "ctx": cmd_ctx,
        "l": lambda: cmd_log(arg), "log": lambda: cmd_log(arg),
        "u": cmd_usage, "usage": cmd_usage,
        "h": cmd_help, "help": cmd_help,
    }

    fn = commands.get(cmd)
    if fn:
        fn()
    else:
        print(f"알 수 없는 명령: {cmd}")
        cmd_help()


if __name__ == "__main__":
    main()

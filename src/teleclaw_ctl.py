#!/usr/bin/env python3
"""TeleClaw CLI — 텔레그램/콘솔 양쪽에서 사용 가능한 명령어 도구.

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
LOG_FILE = LOGS_DIR / "teleclaw.log"

from .messages import msg
from .config import PROJECTS

SESSION_NAMES = list(PROJECTS.keys())
CWD_MAP = {}
for name, info in PROJECTS.items():
    cwd = info["cwd"]
    CWD_MAP[cwd] = name
    CWD_MAP[cwd.replace("/", "\\")] = name


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
            print(msg("svctl_specify_session", names=", ".join(SESSION_NAMES)))
            return None
        return name
    # 대소문자 무시 매칭
    for n in SESSION_NAMES + ["teleclaw"]:
        if n.lower() == arg.lower():
            return n
    print(msg("svctl_session_not_found", name=arg, available=", ".join(SESSION_NAMES) + ", teleclaw"))
    return None


def _get_all_processes():
    """claude.exe + teleclaw 관련 python 프로세스를 모두 조회한다.

    Returns:
        {"sessions": {name: {pid, mem_mb}},
         "manual": [{pid, mem_mb}],
         "infra": [{pid, mem_mb, label}]}
    """
    import re as _re
    # claude + teleclaw 관련 프로세스 조회 (크로스 플랫폼)
    try:
        import psutil
        lines = []
        for proc in psutil.process_iter(["pid", "name", "memory_info", "cmdline"]):
            try:
                info = proc.info
                pname = (info["name"] or "").lower()
                cmdline = " ".join(info["cmdline"] or [])
                mem = info["memory_info"].rss if info["memory_info"] else 0
                if "claude" in pname or ("python" in pname and ("supervisor" in cmdline or "teleclaw" in cmdline)):
                    lines.append(f"{info['pid']}|{info['name']}|{mem}|{cmdline[:200]}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        # psutil 없으면 Windows에서만 PowerShell fallback
        if sys.platform == "win32":
            ps_cmd = (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -eq 'claude.exe' -or "
                "($_.Name -eq 'python.exe' -and ($_.CommandLine -match 'supervisor' -or $_.CommandLine -match 'teleclaw')) } | "
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
        else:
            print(msg("svctl_need_psutil"))
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

        # python teleclaw 프로세스
        if "python" in proc_name.lower():
            if "teleclaw_daemon" in cmdline or "teleclaw-wrapper" in cmdline or "supervisor-wrapper" in cmdline:
                infra.append({"pid": pid, "mem_mb": mem_mb, "label": "daemon"})
            elif "supervisor" in cmdline or "teleclaw" in cmdline:
                infra.append({"pid": pid, "mem_mb": mem_mb, "label": "teleclaw"})
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
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        cores = psutil.cpu_count()
        mem = psutil.virtual_memory()
        print(msg("sys_cpu", pct=cpu, cores=cores))
        print(msg("sys_mem", used=mem.used / (1024**3), total=mem.total / (1024**3), pct=mem.percent))
    except ImportError:
        print(msg("svctl_need_psutil"))
    except Exception as e:
        print(msg("svctl_error", name="sys", error=str(e)))


def cmd_ps():
    """관련 프로세스 목록 및 상태."""
    all_procs = _get_all_processes()
    hub_data = {}

    # TeleClaw 상태
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
        print(msg("svctl_sv_running", pid=sv_pid, h=h, m=m))
    else:
        print(msg("svctl_sv_not_running"))

    # 인프라 프로세스 (래퍼, teleclaw python)
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

    print(msg("svctl_total", mem=total_mb))


def cmd_restart(arg, mode="resume"):
    name = _resolve_name(arg)
    if not name:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if name.lower() == "teleclaw":
        flag = DATA_DIR / "restart_request_teleclaw.flag"
        flag.write_text("force")
        print(msg("svctl_restart_sv"))
    else:
        flag = DATA_DIR / f"restart_request_{name}.flag"
        parts = ["force"]
        if mode != "resume":
            parts.append(mode)
        flag.write_text(",".join(parts))
        mode_str = f" ({mode})" if mode != "resume" else ""
        print(msg("svctl_restart_session", name=name, mode=mode_str))



def cmd_pause(arg):
    """세션을 일시정지 — 프로세스 종료 + TeleClaw가 재시작하지 않음."""
    name = _resolve_name(arg)
    if not name or name.lower() == "teleclaw":
        print(msg("svctl_specify_session_no_sv"))
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    flag = DATA_DIR / f"pause_{name}.flag"
    flag.write_text(str(int(time.time())))
    # 프로세스 종료
    all_procs = _get_all_processes()
    pi = all_procs["sessions"].get(name)
    if pi and pi.get("pid"):
        try:
            from .process_utils import kill_pid
            kill_pid(pi["pid"])
            print(msg("svctl_paused", name=name, pid=pi['pid']))
        except Exception:
            print(msg("svctl_pause_flag_only", name=name))
    else:
        print(msg("svctl_paused_no_proc", name=name))


def cmd_log(arg):
    n = int(arg) if arg and arg.isdigit() else 20
    n = min(n, 50)
    if not LOG_FILE.exists():
        print(msg("svctl_no_log"))
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
        print(msg("svctl_cred_fail", error=str(e)))
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
            print(msg("svctl_usage_fail_http", code=r.status_code))
            return
        data = r.json()
    except Exception as e:
        print(msg("svctl_usage_fail", error=str(e)))
        return

    from datetime import datetime, timezone

    from .usage_fmt import usage_bar as _bar, reset_str as _reset_str

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
        print(msg("svctl_no_session_ids"))
        return
    ids = json.loads(SESSION_IDS_FILE.read_text(encoding="utf-8"))
    for name in SESSION_NAMES:
        info = ids.get(name)
        if not info:
            print(msg("svctl_no_session", name=name))
            continue
        sid = info.get("session_id", "")
        proj_dir = PROJECT_DIRS.get(name)
        if not proj_dir or not sid:
            print(msg("svctl_no_mapping", name=name))
            continue
        jsonl = SESSIONS_BASE / proj_dir / f"{sid}.jsonl"
        if not jsonl.exists():
            print(msg("svctl_no_transcript", name=name))
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
                    emsg = entry.get("message", {})
                    u = emsg.get("usage")
                    if u:
                        last_usage = u
                    m = emsg.get("model", "")
                    if m:
                        last_model = m
            if not last_usage:
                print(msg("svctl_no_usage", name=name))
                continue
            inp = last_usage.get("input_tokens", 0)
            cache_create = last_usage.get("cache_creation_input_tokens", 0)
            cache_read = last_usage.get("cache_read_input_tokens", 0)
            total = inp + cache_create + cache_read
            # 모델별 컨텍스트 크기
            CTX_SIZES = {"opus": 1000000, "1m": 1000000, "sonnet": 200000, "haiku": 200000}
            ctx_size = next((v for k, v in CTX_SIZES.items() if k in last_model), 200000)
            pct = total / ctx_size * 100
            bar_filled = round(pct / 5)
            bar = "|" * bar_filled + "." * (20 - bar_filled)
            print(f"  {name}: {bar} {pct:.0f}% ({total:,}/{ctx_size:,})")
        except Exception as e:
            print(msg("svctl_error", name=name, error=str(e)))


def cmd_help():
    print(msg("svctl_help"))
    print()
    print(f"  {', '.join(SESSION_NAMES)}, teleclaw")


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
        "sv": lambda: cmd_restart("teleclaw"), "teleclaw": lambda: cmd_restart("teleclaw"),
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
        print(msg("svctl_unknown_cmd", cmd=cmd))
        cmd_help()


if __name__ == "__main__":
    main()

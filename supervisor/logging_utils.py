"""로깅 및 단일 인스턴스 보장"""

import os
import json
import time

from .config import LOG_FILE, LOCK_FILE

# --- 로깅 ---

_log_line_count = 0

def log(msg: str):
    global _log_line_count
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("utf-8", errors="replace").decode("ascii", errors="replace"), flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        _log_line_count += 1
        if _log_line_count >= 100:
            _log_line_count = 0
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > 500:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines[-500:])
    except Exception:
        pass


# --- 단일 인스턴스 보장 ---

def _find_existing_supervisor() -> int | None:
    """이미 실행 중인 supervisor.py 프로세스 PID 반환. 없으면 None."""
    import subprocess
    my_pid = os.getpid()
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             "Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | "
             "ForEach-Object { Write-Output (\"$($_.ProcessId),$($_.CommandLine)\") }"],
            capture_output=True, text=True, timeout=10
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # supervisor.py만 매칭 (supervisor-wrapper 등 제외)
            if "supervisor.py" not in line or "supervisor-" in line:
                continue
            comma = line.index(",")
            try:
                pid = int(line[:comma])
                if pid != my_pid:
                    return pid
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    return None


def _write_lock():
    try:
        with open(LOCK_FILE, "w") as f:
            json.dump({"pid": os.getpid(), "started": time.time()}, f)
    except Exception:
        pass


def _release_lock():
    try:
        os.remove(LOCK_FILE)
    except Exception:
        pass

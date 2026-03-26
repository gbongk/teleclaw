"""크로스 플랫폼 프로세스 유틸 — tasklist/taskkill/powershell 대체."""

import os
import signal
import sys


def is_pid_alive(pid: int) -> bool:
    """PID가 실행 중인지 확인. 크로스 플랫폼."""
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass
    # psutil 없으면 OS 별 폴백
    if sys.platform == "win32":
        import subprocess
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5)
        return str(pid) in r.stdout
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def kill_pid(pid: int):
    """PID 강제 종료. 크로스 플랫폼."""
    try:
        import psutil
        p = psutil.Process(pid)
        p.kill()
        return
    except ImportError:
        pass
    except Exception:
        pass
    if sys.platform == "win32":
        import subprocess
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=5)
    else:
        os.kill(pid, signal.SIGKILL)


def find_processes(name_pattern: str):
    """이름 패턴으로 프로세스 검색. [(pid, name, cmdline), ...] 반환."""
    try:
        import psutil
        results = []
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                info = p.info
                pname = info["name"] or ""
                cmdline = " ".join(info["cmdline"] or [])
                if name_pattern.lower() in pname.lower() or name_pattern.lower() in cmdline.lower():
                    results.append((info["pid"], pname, cmdline))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return results
    except ImportError:
        return []

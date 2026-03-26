"""로깅 및 단일 인스턴스 보장"""

import os
import sys
import json
import time

from .config import LOG_FILE, LOCK_FILE, LOGS_DIR

# --- 로깅 ---

_log_line_count = 0


def _archive_lines(lines: list[str]):
    """잘린 로그를 날짜별 파일에 보관. 7일 초과 아카이브 자동 삭제."""
    try:
        date_str = time.strftime("%Y-%m-%d")
        archive_path = os.path.join(LOGS_DIR, f"teleclaw_{date_str}.log")
        with open(archive_path, "a", encoding="utf-8") as f:
            f.writelines(lines)
        # 7일 초과 아카이브 삭제
        import glob, datetime
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        for path in glob.glob(os.path.join(LOGS_DIR, "teleclaw_????-??-??.log")):
            fname = os.path.basename(path)
            date_part = fname.replace("teleclaw_", "").replace(".log", "")
            if date_part < cutoff:
                os.remove(path)
    except Exception:
        pass

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
                # 잘리는 로그를 날짜별 파일에 보관
                _archive_lines(lines[:-500])
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines[-500:])
    except Exception as e:
        print(f"[logging] 로그 파일 쓰기 실패: {e}", file=sys.stderr, flush=True)


# --- 단일 인스턴스 보장 ---

def _find_existing_teleclaw() -> int | None:
    """이미 실행 중인 teleclaw 프로세스 PID 반환. lock file 기반."""
    import subprocess
    my_pid = os.getpid()
    if not os.path.exists(LOCK_FILE):
        return None
    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        pid = data.get("pid", 0)
        if pid == my_pid or pid == 0:
            return None
        from .process_utils import is_pid_alive
        if is_pid_alive(pid):
            return pid
    except Exception as e:
        print(f"[logging] 기존 teleclaw 탐색 실패: {e}", file=sys.stderr, flush=True)
    return None


def _write_lock():
    try:
        with open(LOCK_FILE, "w") as f:
            json.dump({"pid": os.getpid(), "started": time.time()}, f)
    except Exception as e:
        print(f"[logging] lock 파일 쓰기 실패: {e}", file=sys.stderr, flush=True)


def _release_lock():
    try:
        os.remove(LOCK_FILE)
    except Exception as e:
        print(f"[logging] lock 파일 삭제 실패: {e}", file=sys.stderr, flush=True)

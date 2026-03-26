"""프로젝트 설정, 경로, 상수 — config.yaml에서 로드"""

import os
import sys

# --- config.yaml 로드 ---

_SUPERVISOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_SUPERVISOR_DIR, "config.yaml")


def _load_yaml(path: str) -> dict:
    """PyYAML 없이 간단한 YAML 파싱. 중첩 1단계만 지원."""
    if not os.path.exists(path):
        print(f"[config] config.yaml not found: {path}", file=sys.stderr)
        print(f"[config] cp config.example.yaml config.yaml 후 설정하세요", file=sys.stderr)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    result = {}
    current_section = None
    current_item = None

    for line in lines:
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())

        if indent == 0 and ":" in stripped:
            key, _, val = stripped.partition(":")
            val = val.strip().strip('"').strip("'")
            if val:
                result[key.strip()] = val
            else:
                result[key.strip()] = {}
                current_section = key.strip()
                current_item = None
        elif indent == 2 and current_section and ":" in stripped:
            key, _, val = stripped.partition(":")
            val = val.strip().strip('"').strip("'")
            if val:
                if current_item and isinstance(result[current_section].get(current_item), dict):
                    result[current_section][current_item][key.strip()] = val
                else:
                    result[current_section][key.strip()] = val
            else:
                current_item = key.strip()
                result[current_section][current_item] = {}
        elif indent == 4 and current_section and current_item and ":" in stripped:
            key, _, val = stripped.partition(":")
            val = val.strip().strip('"').strip("'")
            result[current_section][current_item][key.strip()] = val

    return result


_cfg = _load_yaml(_CONFIG_PATH)

# --- 프로젝트 설정 ---

CHAT_ID = _cfg.get("chat_id", "")

PROJECTS = {}
for name, info in _cfg.get("projects", {}).items():
    if isinstance(info, dict) and "bot_token" in info:
        PROJECTS[name] = {
            "cwd": info.get("cwd", ""),
            "bot_token": info["bot_token"],
            "bot_id": info.get("bot_id", info["bot_token"].split(":")[0]),
            "mcp_json": os.path.join(info.get("cwd", ""), ".mcp.json"),
        }

# --- 경로 ---

SUPERVISOR_DIR = _SUPERVISOR_DIR
LOGS_DIR = os.path.join(SUPERVISOR_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "supervisor.log")
LOCK_FILE = os.path.join(LOGS_DIR, "supervisor.lock")
STATUS_FILE = os.path.join(LOGS_DIR, "hub_status.json")
SESSION_IDS_FILE = os.path.join(LOGS_DIR, "session_ids.json")
DATA_DIR = os.path.join(SUPERVISOR_DIR, "data")
TELEGRAM_DIR = DATA_DIR
CLAUDE_SESSIONS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "sessions")

# --- 상수 ---

HEALTH_CHECK_INTERVAL = 120  # 2분
STUCK_THRESHOLD = 1800  # 30분
MAX_RESTARTS_PER_WINDOW = 3
RESTART_WINDOW = 1800  # 30분
SESSION_RESET_QUERIES = 100
SESSION_RESET_HOURS = 6
AUTO_RESUME_ENABLED = True

AUTO_RESUME_MODE = "resume"
AUTO_RESUME_PROMPTS = {
    "resume": "[시스템 재시작됨] 직전에 수행하던 작업이 완료되지 않았다면 이어서 진행해줘. 완료되었다면 대기해줘.",
    "check": "[시스템 재시작됨] 직전에 수행하던 작업이 무엇이었는지 간단히 알려줘. 이어서 진행하지는 마.",
    "none": None,
}

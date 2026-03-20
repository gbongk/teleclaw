"""프로젝트 설정, 경로, 상수"""

import os

# --- 프로젝트 설정 ---

PROJECTS = {
    "Converter": {
        "cwd": "D:/workspace/converter",
        "bot_token": "8590076448:AAHea0Rwj568h5-qcT4aqhSwsf2maGKA-2Y",
        "bot_id": "8590076448",
        "mcp_json": "D:/workspace/converter/.mcp.json",
    },
    "NemoNemo": {
        "cwd": "D:/workspace/android/NemoNemo",
        "bot_token": "8774339137:AAHXzjGno8SYLvuUGgJERoEkb7WlcqjCmqQ",
        "bot_id": "8774339137",
        "mcp_json": "D:/workspace/android/NemoNemo/.mcp.json",
    },
    "Crossword": {
        "cwd": "D:/workspace/android/Crossword",
        "bot_token": "8765213028:AAG7TGP2tBz9VmcckCFP09rIOD2XdWHE-l0",
        "bot_id": "8765213028",
        "mcp_json": "D:/workspace/android/Crossword/.mcp.json",
    },
}

CHAT_ID = "8510879138"
SUPERVISOR_DIR = "D:/workspace/supervisor"
LOGS_DIR = os.path.join(SUPERVISOR_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "supervisor.log")
LOCK_FILE = os.path.join(LOGS_DIR, "supervisor.lock")
STATUS_FILE = os.path.join(LOGS_DIR, "hub_status.json")
SESSION_IDS_FILE = os.path.join(LOGS_DIR, "session_ids.json")
DATA_DIR = os.path.join(SUPERVISOR_DIR, "data")
TELEGRAM_DIR = DATA_DIR  # flag 파일 호환용 별칭

# --- 상수 ---

HEALTH_CHECK_INTERVAL = 120  # 2분
STUCK_THRESHOLD = 1800  # 30분
MAX_RESTARTS_PER_WINDOW = 3
RESTART_WINDOW = 1800  # 30분
SESSION_RESET_QUERIES = 100
SESSION_RESET_HOURS = 6

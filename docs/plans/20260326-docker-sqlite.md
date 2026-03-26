# Docker + SQLite 전환 계획

## 현재 상태

### flag 파일 (7종)
| 파일 | 포맷 | 용도 |
|---|---|---|
| `pause_{name}.flag` | 타임스탬프 텍스트 | 일시정지 |
| `restart_request_{name}.flag` | 토큰 텍스트 (force,reset 등) | 재시작 요청 |
| `restart_request_supervisor.flag` | "force" 텍스트 | 슈퍼바이저 재시작 |
| `relay_enabled_{bot_id}_{chat_id}.flag` | 존재 여부만 | relay 활성화 |

### JSON 상태 파일 (3종)
| 파일 | 용도 |
|---|---|
| `hub_status.json` | 슈퍼바이저/세션 상태 스냅샷 |
| `session_ids.json` | 세션 ID + auto-resume 상태 |
| `last_offset_{bot_id}.json` | 텔레그램 폴링 offset |

## SQLite 스키마

```sql
-- 세션 상태
CREATE TABLE sessions (
    name TEXT PRIMARY KEY,
    status TEXT DEFAULT 'idle',           -- idle/connected/busy/paused/dead/stuck
    session_id TEXT,
    pid INTEGER,
    query_count INTEGER DEFAULT 0,
    restart_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    was_busy INTEGER DEFAULT 0,
    no_resume INTEGER DEFAULT 0,
    start_time REAL,
    updated_at REAL
);

-- 명령 큐 (flag 파일 대체)
CREATE TABLE commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,                  -- 세션명 또는 "supervisor"
    command TEXT NOT NULL,                 -- restart/pause/wakeup/reset
    args TEXT DEFAULT '',                  -- force, noresume, resume, reset 등
    created_at REAL,
    processed INTEGER DEFAULT 0
);

-- relay 설정
CREATE TABLE relay_config (
    bot_id TEXT,
    chat_id TEXT,
    enabled INTEGER DEFAULT 1,
    PRIMARY KEY (bot_id, chat_id)
);

-- 텔레그램 폴링 offset
CREATE TABLE poll_offsets (
    bot_id TEXT PRIMARY KEY,
    offset INTEGER DEFAULT 0,
    updated_at REAL
);
```

## 변경 대상

### hub/state_db.py (신규)
- SQLite 래퍼 클래스
- flag 파일과 동일한 API 제공
- `get_command()`, `set_session_status()`, `is_relay_enabled()` 등

### supervisor.py 변경
- `_restart_flag_loop` → DB 폴링
- `_write_status()` → DB 업데이트
- `_save_session_ids()` / `_load_session_ids()` → DB
- `_save_offset()` / `_load_offset()` → DB

### relay_common.py 변경
- `is_relay_enabled()` → DB 쿼리
- `is_supervised_session()` → DB 쿼리

### commands.py 변경
- `/pause`, `/restart`, `/reset` → DB insert

## Docker

### Dockerfile
- python:3.11-slim 베이스
- Claude Code CLI 설치
- requirements.txt 설치
- volume: config.yaml, data/ (SQLite DB)

### docker-compose.yml
- 볼륨 마운트: 프로젝트 디렉토리, config, DB
- 환경변수로 설정 오버라이드 가능

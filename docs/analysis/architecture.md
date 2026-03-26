# TeleClaw 아키텍처

## 개요

Claude Code SDK 기반 텔레그램 봇 관리 시스템.
텔레그램 메시지 수신 → SDK query → 응답 → 텔레그램 전송.
N개 세션(프로젝트별) 동시 관리. config.yaml에서 프로젝트 정의.

주요 특징:
- **채널 추상화** — Channel 인터페이스로 텔레그램 외 플랫폼 확장 가능
- **i18n** — ko/en 메시지 분리 (messages.py, config.yaml의 `lang` 설정)
- **크로스플랫폼** — Windows(schtasks) / Linux(systemd) 서비스 등록
- **SQLite 상태 관리** — flag 파일/JSON 대신 state_db.py로 통합
- **pip 설치 가능** — pyproject.toml 기반 (`pip install .`, `teleclaw` CLI)

## 파일 구조

```
D:/workspace/supervisor/
├── hub/                             ← 패키지 (python -m hub 또는 teleclaw CLI)
│   ├── __init__.py                 ← 공개 클래스 re-export, CLI 진입점 (서브커맨드 라우팅)
│   ├── __main__.py                 ← python -m hub 진입점
│   ├── config.py                   ← config.yaml 로드, 프로젝트 설정, 경로, 상수
│   ├── logging_utils.py            ← 로깅 (500줄 로테이션 + 날짜별 아카이브), 단일 인스턴스 lock
│   ├── telegram_api.py             ← 텔레그램 API (sync/async), 텍스트 변환
│   ├── channel.py                  ← Channel 추상 인터페이스 (ABC)
│   ├── channel_telegram.py         ← TelegramChannel — Channel의 텔레그램 구현체
│   ├── messages.py                 ← i18n 메시지 (ko/en), msg() 함수
│   ├── session.py                  ← SessionState 데이터클래스
│   ├── commands.py                 ← /명령어 핸들러, 사용량 조회
│   ├── state_db.py                 ← SQLite 상태 관리 (세션, 명령 큐, relay, offset)
│   ├── process_utils.py            ← 크로스플랫폼 프로세스 유틸 (is_pid_alive, kill_pid, find_processes)
│   ├── service.py                  ← 시스템 서비스 등록/해제 (systemd / schtasks)
│   ├── usage_fmt.py                ← 사용량 포맷 유틸 (usage_bar, reset_str)
│   └── teleclaw.py                 ← TeleClaw 클래스 (루프, 연결, 재시작)
├── teleclaw-wrapper.py              ← 래퍼 (자동 재시작 + 백오프 + 비상 명령)
├── svctl.py                         ← CLI 제어 도구 (세션 재시작, 로그, 사용량 등)
├── relay-stop.py                    ← Stop 훅 (응답 텔레그램 중계)
├── relay-tool-use.py                ← PostToolUse 훅 (도구 사용 중계)
├── relay-screenshot.py              ← 스크린샷 릴레이
├── relay_common.py                  ← 릴레이 공통 유틸
├── send_telegram.py                 ← CLI 전송 도구 (photo/file)
├── config.yaml                      ← 실제 설정 (git 미추적)
├── config.example.yaml              ← 설정 예제
├── pyproject.toml                   ← pip install 가능 (teleclaw CLI)
├── data/                            ← 런타임 데이터 (teleClaw.db)
├── logs/                            ← 로그 (teleclaw.log, teleclaw.lock, 날짜별 아카이브)
└── docs/analysis/                   ← 이 문서
```

## 모듈 역할

### config.py (~107줄)
- `_load_yaml()` — PyYAML 없이 간단한 YAML 파싱 (중첩 1단계)
- config.yaml에서 로드: `CHAT_ID`, `LANG`, `ALLOWED_USERS`, `PROJECTS`
- `PROJECTS` 딕셔너리 (프로젝트별 cwd, bot_token, bot_id, mcp_json)
- `ALLOWED_USERS` — config.yaml의 `allowed_users` + `chat_id` 합집합
- 경로 상수: `SUPERVISOR_DIR`, `LOGS_DIR`, `LOG_FILE`, `LOCK_FILE`, `STATUS_FILE`, `SESSION_IDS_FILE`, `DATA_DIR`
- 임계값: `HEALTH_CHECK_INTERVAL(120s)`, `STUCK_THRESHOLD(1800s)`, `MAX_RESTARTS_PER_WINDOW(3)`, `RESTART_WINDOW(1800s)`
- `AUTO_RESUME_MODE = "resume"` — 자동 재시작 시 기본 재개 모드

### logging_utils.py (~92줄)
- `log()` — 타임스탬프 로그 (콘솔 + 파일, 500줄 로테이션 + 날짜별 아카이브, 7일 자동 삭제)
- `_find_existing_teleclaw()` — lock 파일 + psutil로 기존 프로세스 탐지
- `_write_lock()` / `_release_lock()` — 단일 인스턴스 lock

### channel.py (~114줄)
- `Channel` ABC — 메시징 플랫폼 공통 인터페이스
- 추상 메서드: `poll()`, `send()`, `edit()`, `delete()`, `react()`, `send_sync()`, `send_photo()`, `send_file()`
- 기본 구현: `format()`, `split()`, `broadcast_sync()`, `broadcast()`
- 동기 파일 전송: `send_photo_sync()`, `send_file_sync()` (CLI/훅용)
- 파일 다운로드: `download_file()` (file_ref → bytes)
- 프로퍼티: `name`, `max_length`

### channel_telegram.py (~198줄)
- `TelegramChannel(Channel)` — Channel의 텔레그램 구현체
- 내부적으로 `telegram_api.py` 함수를 래핑 (하위 호환 유지)
- 폴링: `poll()` → getUpdates, 메시지/편집/이미지/문서 파싱
- 전송: `send()`, `edit()`, `delete()`, `react()` (async)
- 동기: `send_sync()` (commands.py용)
- 파일: `send_photo()`, `send_file()`, `send_photo_sync()`, `send_file_sync()`
- 다운로드: `download_file()` (getFile → download)
- 포맷: `format()` (마크다운 → HTML), `split()` (메시지 분할)
- 브로드캐스트: `broadcast_sync()`, `broadcast()` (전체 봇 알림)
- offset 관리: `get_offset()`, `set_offset()`

### messages.py (~518줄)
- `msg(key, **kwargs)` — 현재 언어(LANG)의 메시지 반환, kwargs 포맷팅
- `_MESSAGES` 딕셔너리 — ko/en 메시지 정의
- 카테고리: TeleClaw 상태, 세션 재시작, 세션 에러, 자동 재개, 진행 상태, pause/wakeup, interrupt, /ask, /status, /usage, /ctx, /sys, /log, /help, wrapper, svctl

### telegram_api.py (~404줄)
- 동기: `send_telegram()`, `edit_telegram()`, `send_ack()`, `send_photo_sync()`, `send_file_sync()`
- 비동기: `async_send_telegram()`, `async_edit_telegram()`, `async_react()`, `async_send_photo()`, `async_send_file()`, `async_notify_all()`
- 텍스트: `_clean_text()`, `_escape_html()`, `_md_to_telegram_html()`, `_split_message()`, `_convert_table_to_list()`
- 유틸: `_notify_all()` (전체 봇 알림)

### session.py (~30줄)
- `SessionState` 데이터클래스 — 프로젝트별 세션 상태
- 주요 필드: client, channel, connected, busy, message_queue, session_id, query_count, restart_count, restart_history, resume_count, was_busy_before_restart, no_resume_before_restart, last_restart_mode

### state_db.py (~242줄)
- SQLite 기반 상태 관리 (flag 파일 + JSON 상태 파일 대체)
- 테이블: `sessions`, `commands`, `relay_config`, `poll_offsets`, `supervisor_state`
- 세션: `set_session()`, `get_session()`, `get_all_sessions()`, `delete_session()`
- 명령 큐: `push_command()`, `pop_command()`, `pop_commands()`, `has_pending_command()`
- relay 설정: `set_relay()`, `is_relay_enabled()`
- 폴링 offset: `set_offset()`, `get_offset()`
- 전역 상태: `set_state()`, `get_state()`
- 하위 호환: `is_paused()`, `set_paused()`
- 정리: `cleanup_old_commands()`

### commands.py (~338줄)
- `handle_command(teleclaw, text, channel)` — 명령어 라우팅
- `_get_usage()` — Anthropic OAuth API 사용량 조회 (60초 캐시)
- 명령어: /status, /usage, /ctx, /sys, /log, /esc, /pause, /restart, /reset, /ask, /help

### process_utils.py (~65줄)
- `is_pid_alive(pid)` — PID 실행 확인 (psutil → tasklist/kill 폴백)
- `kill_pid(pid)` — PID 강제 종료 (psutil → taskkill/SIGKILL 폴백)
- `find_processes(pattern)` — 이름 패턴으로 프로세스 검색

### service.py (~171줄)
- `install()` / `uninstall()` / `status()` / `logs()` — 크로스플랫폼 공통 인터페이스
- Linux: systemd user service (`~/.config/systemd/user/teleclaw.service`)
- Windows: Task Scheduler (`schtasks /create /tn TeleClaw`)
- `teleclaw install/uninstall/status/logs` CLI 서브커맨드로 호출

### usage_fmt.py (~41줄)
- `usage_bar(pct)` — 20칸 바 포맷 (색상 아이콘)
- `reset_str(bucket)` — 리셋 시간까지 남은 시간 문자열

### hub/teleclaw.py (~1347줄)
- `TeleClaw` 클래스:
  - `start()` — 초기화, DB init, 채널 생성, **세션 병렬 연결 (asyncio.gather)**, 루프 시작
  - `_session_loop()` — 메시지 큐에서 꺼내 SDK query, 스트리밍 응답 텔레그램 전송, **경로별 독립 재시도** (retry_noclient/retry_conn/retry_timeout/retry_error). **TeleClaw 시작 시 auto-resume 없음 (대기 모드)**. **첫 메시지 3초 버퍼링** — 빠른 응답은 editMessage 없이 최종 sendMessage 한 번으로 전송
  - `_bot_poll_loop()` — TelegramChannel.poll() 기반 메시지 수신, 큐에 적재, **ALLOWED_USERS 화이트리스트 필터링**, **에러 시 repr(e)+traceback 로깅**
  - `_health_check_loop()` — 2분 주기 DEAD/STUCK 감지 → 자동 재시작. **진행 알림 간격 120초**
  - `_restart_flag_loop()` — 1초 주기 state_db 명령 큐 폴링 (restart/pause/wakeup), **busy 시 graceful shutdown (최대 60초 대기)**
  - `_watchdog_loop()` — asyncio 데드락 감지 (5분 무응답 → 강제 종료)
  - `_connect_session()` / `_restart_session()` — SDK 연결/재시작. **`mode="reset"` 시 session_id 초기화**
  - `_safe_disconnect()` — 프로세스 직접 terminate (client.disconnect() CPU 100% 이슈 회피)
  - `_wait_mcp_ready()` — MCP 서버 초기화 대기
  - `_format_tool_line()` — **도구 4개 초과 시 `처음2 → ...+N → 마지막1` 축약**
  - `_should_auto_resume()` — 자동 재개 조건 판단
  - `_broadcast_sync()` / `_broadcast()` — 전체 채널 알림
  - `_write_status()` — 상태 파일 기록
- `main()` — 진입점 (lock 획득, 시그널 등록, start). **`[HUB]` 프리픽스로 TeleClaw 본체 이벤트 구분**
- monkey-patch: 알 수 없는 메시지 타입 (rate_limit_event 등) 무시

## 설정 (config.yaml)

```yaml
lang: "ko"                    # 언어 (ko/en)
chat_id: "123456789"          # 텔레그램 채팅 ID
allowed_users: ""             # 허용 사용자 ID (쉼표 구분, 비어있으면 chat_id만)

projects:
  MyProject:
    cwd: "/path/to/project"
    bot_token: "BOT_TOKEN"
```

## 실행 계층

```
시스템 서비스 (systemd/schtasks)
  └── teleclaw-wrapper.py (자동 재시작 + 백오프)
        └── python -m hub (패키지 진입점) 또는 teleclaw CLI
              └── TeleClaw 클래스
                    ├── N× _bot_poll_loop (TelegramChannel.poll())
                    ├── N× _session_loop (SDK query)
                    ├── _restart_flag_loop (state_db 명령 큐 감시)
                    ├── _health_check_loop (건강 감시)
                    └── _watchdog_loop (데드락 감지)
```

### CLI 서브커맨드 (teleclaw 또는 python -m hub)

| 명령 | 설명 |
|---|---|
| `teleclaw` | TeleClaw 실행 |
| `teleclaw install` | 시스템 서비스 등록 + 자동 시작 |
| `teleclaw uninstall` | 시스템 서비스 해제 |
| `teleclaw status` | 서비스 상태 확인 |
| `teleclaw logs [N]` | 서비스 로그 (기본 50줄) |

## 메시지 흐름

```
사용자 → 텔레그램 봇
  → _bot_poll_loop: TelegramChannel.poll() → ALLOWED_USERS 필터 → message_queue.put()
  → _session_loop: message_queue.get()
    → SDK 버퍼 드레인 (receive_nowait로 잔여 메시지 제거, N턴 밀림 방지)
    → SDK client.query()
    → 스트리밍 응답: AssistantMessage → (3초 버퍼) → channel.edit() (라이브 업데이트)
    → ToolUse → 도구 요약 추가 (_format_tool_line: 4개 초과 시 축약)
    → ResultMessage → 최종 전송
```

### SDK 버퍼 밀림 문제 (2026-03-24 발견)

SDK `_message_receive` 채널(anyio MemoryObjectStream, max_buffer_size=100)에 이전 턴의 잔여 응답이 쌓이면,
다음 `receive_messages()` 호출 시 현재 질문이 아닌 이전 턴의 응답이 반환됨 (N턴 밀림).
Claude 내부는 정상 처리 (파일 쓰기로 검증: test.txt=10 정답, 텔레그램=12 밀림).
해결: `query()` 호출 전에 `_message_receive.receive_nowait()` 루프로 잔여 메시지 드레인.

## Auto-Resume 설계

### 구분
- **TeleClaw 시작** (`_fresh_start=True`): 재개 안 함, 대기 모드
- **세션 개별 재시작** (`_restart_session`): 모드별 재개 (resume/check/none)
- **세션 리셋** (`mode="reset"`): session_id 초기화, 재개 안 함

### Reset 정책
- 기본 재기동 모드: **resume** (모든 자동 재시작)
- reset은 **명시적 요청**(명령 큐/명령어) 또는 **이미지 누적 에러**(컨텍스트 초과)에서만 사용
- 자동 reset 호출: `이미지 누적 에러` 1곳만 (resume으로 해결 불가)

### 안전장치
1. `_session_loop` — TeleClaw 시작 시 auto-resume 없음 (대기 모드)
2. `mode="reset"` — reset 시 session_id 초기화 (`_connect_session`)
3. `resume_count >= 2` — 연속 재개 2회 초과 시 중단 + 텔레그램 알림
4. `session_id` 없으면 재개 안 함 (맥락 유실 = 무한 루프 위험)
5. 명령 큐 경유 재시작 시 `no_resume_before_restart` 초기화 — 사용자 요청이므로 busy 여부 무관하게 resume 허용

### 리셋 시점
- 정상 완료 → resume_count = 0
- 사용자 새 메시지 → resume_count = 0

## 주요 설계 패턴

1. **채널 추상화** — Channel ABC로 텔레그램 의존성 분리. TelegramChannel이 구현. 다른 플랫폼(Discord 등) 확장 가능
2. **큐 기반 디커플링** — 폴링(빠름)과 SDK 처리(느림) 분리
3. **라이브 텔레그램 업데이트** — 응답 스트리밍 중 1초+ 간격으로 메시지 수정 (첫 3초는 버퍼링하여 editMessage 지연 방지)
4. **i18n** — messages.py에 ko/en 메시지 분리, config.yaml `lang` 설정으로 전환
5. **SQLite 상태 관리** — state_db.py가 flag 파일/JSON 대체. 세션 상태, 명령 큐, relay 설정, poll offset 통합
6. **자동 재개** — 세션 개별 재시작(svctl r) 시에만 auto-resume (최대 2회). TeleClaw 시작/reset에서는 미발동
7. **도구 라인 축약** — 4개 초과 시 `처음2 → ...+N → 마지막1` 형태로 컴팩트 표시
8. **세션 영속성** — session_ids.json에 저장, 재시작 시 컨텍스트 복원
9. **`[HUB]` 프리픽스** — TeleClaw 본체 이벤트(시작, 재시작, 건강체크 등)를 세션 응답과 구분
10. **레이트 리밋 적응** — 수정 실패 시 지수 백오프 (1s→5s), 성공 시 점진 복구
11. **중복 제거** — 메시지 ID + 타임스탬프 맵 (100개, 5분 TTL)
12. **병렬 세션 연결** — asyncio.gather로 N개 세션 동시 연결 (~14초, 순차 대비 ~70% 단축)
13. **graceful shutdown** — busy 세션 완료 대기 후 재시작 (최대 60초, force 시 즉시)
14. **allowed_users** — config.yaml 화이트리스트로 무단 접근 차단
15. **크로스플랫폼** — process_utils.py(psutil→OS 폴백), service.py(systemd/schtasks)

## 훅 (hooks)

| 훅 | 파일 | 트리거 |
|---|---|---|
| PostToolUse | `relay-tool-use.py` | 도구 호출 후 — 도구 요약 + ai-chat 응답 중계 |
| Stop | `relay-stop.py` | Claude 응답 완료 후 — 최종 텍스트 텔레그램 중계 |

settings.json에 등록:
```json
"hooks": {
  "PostToolUse": [{"command": "python D:/workspace/supervisor/relay-tool-use.py"}],
  "Stop": [{"command": "python D:/workspace/supervisor/relay-stop.py"}]
}
```

## 래퍼 (teleclaw-wrapper.py)

- TeleClaw 프로세스 감시 + 자동 재시작
- 지수 백오프: 3s → 6s → 12s → ... → 1800s (30분 캡)
- 30초 미만 종료 = 에러 (백오프 적용), 30초 이상 = 정상 (카운터 리셋)
- **반복 알림**: 첫 실패 + 5/10/20/50회마다 텔레그램 알림 재전송
- 비상 텔레그램 명령: /log, /status, /restart, /kill, /ask (백오프 중에도 응답)

## 임계값

| 설정 | 값 | 설명 |
|---|---|---|
| HEALTH_CHECK_INTERVAL | 120s | 건강 체크 주기 |
| STUCK_THRESHOLD | 1800s | 30분 busy = STUCK |
| MAX_RESTARTS_PER_WINDOW | 3 | 30분당 최대 재시작 |
| RESTART_WINDOW | 1800s | 재시작 윈도우 |
| 텔레그램 long poll timeout | 25s | getUpdates 대기 |
| SDK connect timeout | 120s | 초기 연결 |
| Watchdog timeout | 300s | asyncio 무응답 → 강제 종료 |

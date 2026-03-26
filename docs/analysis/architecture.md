# 슈퍼바이저 아키텍처

## 개요

Claude Code SDK 기반 텔레그램 봇 관리 시스템.
텔레그램 메시지 수신 → SDK query → 응답 → 텔레그램 전송.
3개 세션(NemoNemo, Crossword, Converter) 동시 관리.

## 파일 구조

```
D:/workspace/supervisor/
├── hub/                           ← 패키지 (python -m hub로 실행)
│   ├── __init__.py               ← 공개 클래스 re-export
│   ├── __main__.py               ← python -m hub 진입점
│   ├── config.py                 ← 상수, 프로젝트 설정, 경로
│   ├── logging_utils.py          ← 로깅, 단일 인스턴스 보장
│   ├── telegram_api.py           ← 텔레그램 API (sync/async), 텍스트 변환
│   ├── session.py                ← SessionState 데이터클래스
│   ├── commands.py               ← /명령어 핸들러, 사용량 조회
│   └── supervisor.py             ← Supervisor 클래스 (루프, 연결, 재시작)
├── supervisor-wrapper.py          ← 래퍼 (자동 재시작, 백오프, 비상 명령)
├── supervisor-wrapper.bat         ← 배치 실행기
├── Supervisor.xml                 ← Windows 작업 스케줄러
├── relay-stop.py                  ← Stop 훅 (응답 텔레그램 중계)
├── relay-tool-use.py              ← PostToolUse 훅 (도구 사용 중계)
├── data/                          ← 런타임 데이터 (flag, update_id)
├── logs/                          ← 로그, 상태, lock
└── docs/analysis/                 ← 이 문서
```

## 모듈 역할

### config.py (~45줄)
- `PROJECTS` 딕셔너리 (프로젝트별 cwd, bot_token, bot_id, mcp_json)
- 경로 상수: `SUPERVISOR_DIR`, `LOGS_DIR`, `DATA_DIR`, `TELEGRAM_DIR`
- 임계값: `HEALTH_CHECK_INTERVAL(120s)`, `STUCK_THRESHOLD(1800s)`, `MAX_RESTARTS_PER_WINDOW(3)`, `SESSION_RESET_QUERIES(100)`, `SESSION_RESET_HOURS(6)`
- `AUTO_RESUME_MODE = "resume"` — 자동 재시작 시 기본 재개 모드

### logging_utils.py (~80줄)
- `log()` — 타임스탬프 로그 (콘솔 + 파일, 500줄 로테이션)
- `_find_existing_supervisor()` — WMI로 기존 프로세스 탐지
- `_write_lock()` / `_release_lock()` — 단일 인스턴스 lock

### telegram_api.py (~284줄)
- 동기: `send_telegram()`, `edit_telegram()`, `send_ack()`
- 비동기: `async_send_telegram()`, `async_edit_telegram()`, `async_react()`
- 텍스트: `_clean_text()`, `_escape_html()`, `_md_to_telegram_html()`, `_split_message()`, `_convert_table_to_list()`
- 유틸: `_notify_all()` (전체 봇 알림)

### session.py (~29줄)
- `SessionState` 데이터클래스 — 프로젝트별 세션 상태
- 주요 필드: client, connected, busy, message_queue, session_id, query_count, restart_count, paused

### commands.py (~312줄)
- `handle_command(supervisor, text, bot_token)` — 10개 명령어 라우팅
- `_get_usage()` — Anthropic OAuth API 사용량 조회 (60초 캐시)
- `_find_session_by_token()` — 봇 토큰으로 세션 조회

### hub/supervisor.py (~1080줄)
- `Supervisor` 클래스:
  - `start()` — 초기화, **세션 병렬 연결 (asyncio.gather)**, 루프 시작
  - `_session_loop()` — 메시지 큐에서 꺼내 SDK query, 스트리밍 응답 텔레그램 전송, **경로별 독립 재시도** (retry_noclient/retry_conn/retry_timeout/retry_error). **슈퍼바이저 시작 시 auto-resume 없음 (대기 모드)**. **첫 메시지 3초 버퍼링** — 빠른 응답은 editMessage 없이 최종 sendMessage 한 번으로 전송
  - `_bot_poll_loop()` — 텔레그램 long polling, 메시지 큐에 적재, **에러 시 repr(e)+traceback 로깅**
  - `_health_check_loop()` — 2분 주기 DEAD/STUCK 감지 → 자동 재시작. **진행 알림 간격 120초 (5분→2분)**
  - `_restart_flag_loop()` — 1초 주기 flag 파일 폴링 (restart/pause/wakeup), **busy 시 graceful shutdown (최대 60초 대기)**
  - `_watchdog_loop()` — asyncio 데드락 감지 (5분 무응답 → 강제 종료)
  - `_connect_session()` / `_restart_session()` — SDK 연결/재시작. **`mode="new"` 시 auto-resume 스킵**
  - `_format_tool_line()` — **도구 4개 초과 시 `처음2 → ...+N → 마지막1` 축약**
- `main()` — 진입점 (lock 획득, 시그널 등록, start). **`[HUB]` 프리픽스로 슈퍼바이저 본체 이벤트 구분**
- monkey-patch: `rate_limit_event` 캡처

## 실행 계층

```
작업 스케줄러 (Supervisor.xml)
  └── supervisor-wrapper.py (자동 재시작 + 백오프)
        └── python -m hub (패키지 진입점)
              └── Supervisor 클래스
                    ├── 3× _bot_poll_loop (텔레그램 폴링)
                    ├── 3× _session_loop (SDK query)
                    ├── _restart_flag_loop (flag 감시)
                    ├── _health_check_loop (건강 감시)
                    └── _watchdog_loop (데드락 감지)
```

## 메시지 흐름

```
사용자 → 텔레그램 봇
  → _bot_poll_loop: getUpdates → 필터링/중복제거 → message_queue.put()
  → _session_loop: message_queue.get()
    → SDK 버퍼 드레인 (receive_nowait로 잔여 메시지 제거, N턴 밀림 방지)
    → SDK client.query()
    → 스트리밍 응답: AssistantMessage → (3초 버퍼) → async_edit_telegram (라이브 업데이트)
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
- **슈퍼바이저 시작** (`_fresh_start=True`): 재개 안 함, 대기 모드
- **세션 개별 재시작** (`_restart_session`): 모드별 재개 (resume/check/none)
- **세션 리셋** (`mode="new"`): 재개 안 함

### Reset 정책
- 기본 재기동 모드: **resume** (모든 자동 재시작)
- reset은 **명시적 요청**(flag/명령어) 또는 **이미지 누적 에러**(컨텍스트 초과)에서만 사용
- 자동 reset 호출: `이미지 누적 에러` 1곳만 (resume으로 해결 불가)

### 안전장치
1. `_session_loop` — 슈퍼바이저 시작 시 auto-resume 없음 (대기 모드)
2. `mode="new"` — reset 시 auto-resume 스킵 (`_restart_session` + `_should_auto_resume`)
3. `resume_count >= 2` — 연속 재개 2회 초과 시 중단 + 텔레그램 알림
4. `session_id` 없으면 재개 안 함 (맥락 유실 = 무한 루프 위험)
5. flag 경유 재시작 시 `no_resume_before_restart` 초기화 — 사용자 요청이므로 busy 여부 무관하게 resume 허용

### 리셋 시점
- 정상 완료 → resume_count = 0
- 사용자 새 메시지 → resume_count = 0

## 주요 설계 패턴

1. **큐 기반 디커플링** — 폴링(빠름)과 SDK 처리(느림) 분리
2. **라이브 텔레그램 업데이트** — 응답 스트리밍 중 1초+ 간격으로 메시지 수정 (첫 3초는 버퍼링하여 editMessage 지연 방지)
3. **자동 재개** — 세션 개별 재시작(svctl r) 시에만 auto-resume (최대 2회). 슈퍼바이저 시작/reset에서는 미발동
4. **도구 라인 축약** — 4개 초과 시 `처음2 → ...+N → 마지막1` 형태로 컴팩트 표시
5. **세션 영속성** — session_ids.json에 저장, 재시작 시 컨텍스트 복원
6. **`[HUB]` 프리픽스** — 슈퍼바이저 본체 이벤트(시작, 재시작, 건강체크 등)를 세션 응답과 구분
5. **레이트 리밋 적응** — 수정 실패 시 지수 백오프 (1s→5s), 성공 시 점진 복구
6. **중복 제거** — 메시지 ID + 타임스탬프 맵 (100개, 5분 TTL)
7. **병렬 세션 연결** — asyncio.gather로 3개 세션 동시 연결 (~14초, 순차 대비 ~70% 단축)
8. **graceful shutdown** — busy 세션 완료 대기 후 재시작 (최대 60초, force 시 즉시)

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

## 래퍼 (supervisor-wrapper.py)

- 슈퍼바이저 프로세스 감시 + 자동 재시작
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
| SESSION_RESET_QUERIES | 100 | 100회 query → 자동 리셋 |
| SESSION_RESET_HOURS | 6 | 6시간 → 자동 리셋 |
| 텔레그램 long poll timeout | 25s | getUpdates 대기 |
| SDK connect timeout | 120s | 초기 연결 |
| Watchdog timeout | 300s | asyncio 무응답 → 강제 종료 |

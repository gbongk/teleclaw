# 슈퍼바이저 아키텍처

## 개요

Claude Code SDK 기반 텔레그램 봇 관리 시스템.
텔레그램 메시지 수신 → SDK query → 응답 → 텔레그램 전송.
3개 세션(NemoNemo, Crossword, Converter) 동시 관리.

## 파일 구조

```
D:/workspace/supervisor/
├── supervisor.py                  ← 진입점 (thin wrapper)
├── supervisor/                    ← 패키지
│   ├── __init__.py               ← 공개 클래스 re-export
│   ├── __main__.py               ← python -m supervisor 지원
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

### supervisor.py (패키지 내, ~1010줄)
- `Supervisor` 클래스:
  - `start()` — 초기화, 루프 병렬 시작
  - `_session_loop()` — 메시지 큐에서 꺼내 SDK query, 스트리밍 응답 텔레그램 전송
  - `_bot_poll_loop()` — 텔레그램 long polling, 메시지 큐에 적재
  - `_health_check_loop()` — 2분 주기 DEAD/STUCK 감지 → 자동 재시작
  - `_restart_flag_loop()` — 1초 주기 flag 파일 폴링 (restart/pause/wakeup)
  - `_watchdog_loop()` — asyncio 데드락 감지 (5분 무응답 → 강제 종료)
  - `_connect_session()` / `_restart_session()` — SDK 연결/재시작
- `main()` — 진입점 (lock 획득, 시그널 등록, start)
- monkey-patch: `rate_limit_event` 캡처

## 실행 계층

```
작업 스케줄러 (Supervisor.xml)
  └── supervisor-wrapper.py (자동 재시작 + 백오프)
        └── supervisor.py (진입점)
              └── supervisor/ 패키지 (Supervisor 클래스)
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
  → _session_loop: message_queue.get() → SDK client.query()
    → 스트리밍 응답: AssistantMessage → async_edit_telegram (라이브 업데이트)
    → ToolUse → 도구 요약 추가
    → ResultMessage → 최종 전송
```

## 주요 설계 패턴

1. **큐 기반 디커플링** — 폴링(빠름)과 SDK 처리(느림) 분리
2. **라이브 텔레그램 업데이트** — 응답 스트리밍 중 1초+ 간격으로 메시지 수정
3. **자동 재개** — 재시작 전 busy였으면 자동 resume (최대 2회)
4. **세션 영속성** — session_ids.json에 저장, 재시작 시 컨텍스트 복원
5. **레이트 리밋 적응** — 수정 실패 시 지수 백오프 (1s→5s), 성공 시 점진 복구
6. **중복 제거** — 메시지 ID + 타임스탬프 맵 (100개, 5분 TTL)

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

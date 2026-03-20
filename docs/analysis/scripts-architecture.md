# Scripts 폴더 아키텍처

## 목적

`D:/workspace/mcp/scripts/`는 3개 Claude Code 세션(NemoNemo, Crossword, Converter)의 프로세스 관리, 텔레그램 훅, 에뮬레이터 제어를 담당하는 스크립트 모음이다. supervisor.py(슈퍼바이저)를 중심으로 세션 수명 주기를 자동화하고, 훅 스크립트로 Claude 응답을 텔레그램에 중계한다.

## 스크립트 분류

### 핵심 (세션 관리)

| 스크립트 | 언어 | 역할 |
|---|---|---|
| `supervisor.py` | Python | **[LEGACY]** supervisor.py(슈퍼바이저)로 대체됨 |
| `check-session-status.sh` | Bash | 세션 상태 조회 + 수동 STUCK 세션 재시작 |

### 훅 (Claude Code Hook)

| 스크립트 | 훅 타입 | 역할 |
|---|---|---|
| ~~`check-telegram-pending.sh`~~ | PostToolUse | (삭제됨 — 슈퍼바이저가 대체) |
| `relay-tool-use.py` | PostToolUse | Claude 텍스트 + 도구 요약을 텔레그램으로 중계 |
| `relay-stop.py` | Stop | Claude 응답 완료 시 최종 텍스트를 텔레그램으로 중계 |
| `stop-telegram-check.sh` | Stop | wait 모드 세션의 종료를 block하여 대기 루프 강제 복귀 |

### 에뮬레이터

| 스크립트 | 역할 |
|---|---|
| `emulator-lock.sh` | 에뮬레이터 공유 잠금 (check/lock/unlock) |
| `emu-ui.sh` | adb + uiautomator 기반 UI 요소 조회/탭/스와이프 |
| `ai-player.py` | NemoNemo 자동 게임 플레이어 (시나리오 기반) |
| `stability-test.sh` | NemoNemo Monkey/lifecycle/OOM 안정성 테스트 |

### Deprecated (`_deprecated/`)

| 스크립트 | 대체됨 |
|---|---|
| `watchdog.py` | `supervisor.py`로 대체 |
| `self-restart.py` | supervisor의 restart flag 방식으로 대체 |
| `self-restart.sh` | 동일 |
| `start-session.sh` | supervisor가 직접 `subprocess.Popen`으로 세션 시작 |

## 각 스크립트 상세

### supervisor.py

3개 Claude 세션의 수명 주기를 관리하는 데몬 프로세스.

**실행 방법:**
```bash
python D:/workspace/mcp/scripts/supervisor.py         # 데몬 모드 (세션 시작 + 감시)
python D:/workspace/mcp/scripts/supervisor.py status   # 상태 조회만
```

Task Scheduler로 로그온 시 자동 시작.

### check-session-status.sh

heartbeat 파일 기반으로 세션 상태를 조회하고, STUCK 세션을 수동 재시작한다.

```bash
bash D:/workspace/mcp/scripts/check-session-status.sh              # 상태 출력
bash D:/workspace/mcp/scripts/check-session-status.sh restart       # STUCK → resume 재시작
bash D:/workspace/mcp/scripts/check-session-status.sh restart new   # STUCK → new 재시작
```

메모리 사용량도 함께 표시 (3GB 초과 시 경고).

### ~~check-telegram-pending.sh~~ (삭제됨)

삭제됨 — hub가 대체. 이전에는 PostToolUse 훅으로 매 도구 실행 후 pending flag를 감지하여 경고를 출력했으나, supervisor.py가 폴링을 직접 담당하면서 불필요해짐.

### relay-tool-use.py

PostToolUse 훅. `relay_enabled` 플래그가 활성인 supervised 세션에서만 동작. transcript JSONL에서 마지막 assistant 텍스트를 추출하고, 도구 사용 요약과 함께 텔레그램으로 전송한다. Read/Grep/Glob 등 읽기 전용 도구는 텍스트만 중계하고 도구 요약은 생략.

### relay-stop.py

Stop 훅. Claude 응답이 완료되면 `last_assistant_message`를 텔레그램으로 전송. `wait_for_message` 관련 응답은 스킵.

### stop-telegram-check.sh

Stop 훅. wait 모드(`wait_mode_{SESSION_ID}.flag` 존재) 세션이 응답을 완료하려 할 때 `{"decision": "block"}` JSON을 출력하여 세션 종료를 막고 `wait_for_message(600)` 호출을 강제한다. heartbeat가 10분 이상 만료되면 wait 모드 플래그를 자동 정리.

### emulator-lock.sh

여러 프로젝트가 하나의 에뮬레이터를 공유할 때 충돌 방지.

```bash
bash D:/workspace/mcp/scripts/emulator-lock.sh check           # FREE/LOCKED/EXPIRED
bash D:/workspace/mcp/scripts/emulator-lock.sh lock Converter   # 잠금 획득
bash D:/workspace/mcp/scripts/emulator-lock.sh unlock           # 해제
```

잠금 파일: `D:/workspace/emulator_lock.json`. 5분 후 자동 만료.

### emu-ui.sh

adb `uiautomator dump`로 UI XML을 파싱하여 요소를 조회/조작한다.

```bash
bash D:/workspace/mcp/scripts/emu-ui.sh                   # 전체 UI 요소 목록
bash D:/workspace/mcp/scripts/emu-ui.sh find "텍스트"     # 텍스트/ID로 검색
bash D:/workspace/mcp/scripts/emu-ui.sh tap "resource-id" # 요소 탭
bash D:/workspace/mcp/scripts/emu-ui.sh tap-text "확인"   # 텍스트로 탭
bash D:/workspace/mcp/scripts/emu-ui.sh tree              # UI 계층 트리
bash D:/workspace/mcp/scripts/emu-ui.sh wait-for "btn" 10 # 요소 대기 (최대 10초)
```

디바이스 자동 감지: `EMULATOR_SERIAL` 환경변수 > 에뮬레이터 > 실제 기기.

### ai-player.py

NemoNemo 앱의 adb 기반 자동 플레이어. 좌표 계산으로 그리드 셀을 탭한다.

```bash
python D:/workspace/mcp/scripts/ai-player.py navigate   # 화면 탐색
python D:/workspace/mcp/scripts/ai-player.py play5x5    # 5x5 퍼즐 풀기
python D:/workspace/mcp/scripts/ai-player.py all        # 전체 시나리오
```

시나리오: navigate, play5x5, gameover, daily, settings, all.

### stability-test.sh

NemoNemo 앱 안정성 자동 테스트. Monkey 테스트, lifecycle 스트레스, OOM 테스트를 실행하고 ANR/FATAL/OOM 카운트를 집계한다.

```bash
bash D:/workspace/mcp/scripts/stability-test.sh quick          # 5k 이벤트
bash D:/workspace/mcp/scripts/stability-test.sh monkey-stress  # 50k 이벤트
bash D:/workspace/mcp/scripts/stability-test.sh all            # 전체
```

## supervisor.py 아키텍처 상세 [LEGACY — supervisor.py로 대체됨]

### 클래스 구조

**SessionState** — 개별 세션 상태
- `proc`: subprocess.Popen 객체 (supervisor가 직접 시작한 경우)
- `adopted_pid`: 기존 프로세스를 편입한 경우의 PID
- `origin`: spawned / adopted / restarted / manual
- `session_id`: claude session ID (resume용)
- `restart_history`: 30분 윈도우 내 재시작 시각 리스트
- `restarting`: 재시작 진행 중 플래그 (경합 방지)
- `last_hb_age`: heartbeat 읽기 실패 시 캐시값

**SessionManager** — 전체 세션 관리
- 3개 프로젝트(`NemoNemo`, `Crossword`, `Converter`)의 SessionState를 보유
- 세션별 `threading.RLock`으로 재시작 경합 방지

### 상태 판정 (`assess_health`)

```
OK        — heartbeat 10분 이내
STARTING  — 시작 후 5분 미만 (grace period)
INACTIVE  — heartbeat 10~30분 (작업 중 추정)
STALE     — heartbeat 30분+ 또는 heartbeat 파일 없음 (메시지 없이 대기 중)
STUCK     — heartbeat 30분+ AND pending 메시지 있음
DEAD      — 프로세스 없음
```

자동 재시작 대상: **DEAD**, **STUCK**

### 감시 루프

```
1초 폴링 (메인 루프)
  ├─ restart_request_{name}.flag 감지 → 즉시 재시작
  └─ 120초마다 health_check_all()
       ├─ DEAD/STUCK → restart_session()
       ├─ INACTIVE → 15분마다 텔레그램 알림
       └─ supervisor_status.json 갱신
```

- 30분 윈도우 내 최대 3회 재시작. 초과 시 텔레그램 알림 + 중단.
- watchdog 스레드: 메인 루프가 5분 이상 멈추면 `os._exit(1)`로 강제 종료 (Task Scheduler가 재시작).

### 세션 시작 흐름

1. `subprocess.Popen`으로 `claude --dangerously-skip-permissions` 실행 (`CREATE_NEW_CONSOLE` 플래그)
2. 별도 스레드에서 세션 파일 감시 → session ID 캡처 (30초 타임아웃)
3. resume 모드인 경우: 별도 스레드에서 PowerShell `SendKeys`로 "wait" 입력 (3회 시도, heartbeat로 성공 확인)

### 기존 프로세스 편입 (`scan_existing`)

시작 시 `C:\Users\kok34\.claude\sessions\*.json`에서 살아있는 claude.exe PID를 찾고, 프로젝트 디렉토리가 일치하는 **wait 세션만** `adopted_pid`로 편입. 수동 콘솔 세션은 무시.

### 단일 인스턴스 보장

`D:/workspace/mcp/logs/supervisor.lock` 파일을 `O_CREAT|O_EXCL`로 원자적 생성. 기존 lock이 있으면 PID 생존 여부로 stale 판정.

## 훅 스크립트 동작 원리

### Claude Code Hook 시스템

Claude Code는 `C:\Users\kok34\.claude\settings.json`에 등록된 훅 스크립트를 도구 사용 시점에 실행한다.

- **PostToolUse**: 도구 실행 직후. stdin으로 `{tool_name, tool_input, session_id, transcript_path, ...}` JSON 수신. stdout 출력이 Claude에게 전달됨.
- **Stop**: Claude 응답 완료 직후. stdin으로 `{session_id, last_assistant_message, stop_hook_active, cwd, ...}` JSON 수신. `{"decision": "block", "reason": "..."}` 출력 시 응답 완료를 차단.

### 훅 실행 순서 (매 도구 호출 시)

```
Claude 도구 호출
  → PostToolUse 훅 (병렬 실행)
    ├─ (check-telegram-pending.sh  → 삭제됨, hub가 대체)
    └─ relay-tool-use.py          → 텔레그램 중계
Claude 응답 완료
  → Stop 훅 (순차 실행)
    ├─ stop-telegram-check.sh     → wait 모드면 block
    └─ relay-stop.py              → 텔레그램 중계
```

### relay 훅 필터링

relay 훅은 아래 조건을 모두 만족할 때만 동작:
1. 프로젝트 `.mcp.json`에 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 존재
2. `relay_enabled_{bot_id}_{chat_id}.flag` 파일 존재
3. `supervisor_status.json`에 등록된 PID와 현재 세션 PID 일치 (수동 세션 제외)

## 공유 자원 (파일 기반 통신)

모든 프로세스 간 통신은 파일 시스템으로 이루어진다.

### 텔레그램 상태 (`D:/workspace/mcp/telegram/`)

| 파일 패턴 | 생산자 | 소비자 | 용도 |
|---|---|---|---|
| `pending_{BOT_ID}_{CHAT_ID}.flag` | telegram server | 훅 스크립트, supervisor | 미처리 메시지 존재 |
| `last_heartbeat_{BOT_ID}_{CHAT_ID}.ts` | telegram server | supervisor, 훅 | 마지막 활동 시각 (unix timestamp) |
| `status_{BOT_ID}_{CHAT_ID}.json` | telegram server | check-session-status.sh | 봇 상태 (waiting/working) |
| `wait_mode_{SESSION_ID}.flag` | telegram server | stop-telegram-check.sh | wait 모드 활성 여부 |
| `relay_enabled_{BOT_ID}_{CHAT_ID}.flag` | telegram server | relay-tool-use.py, relay-stop.py | 텔레그램 중계 활성 |
| `restart_request_{NAME}.flag` | Claude 세션 / 외부 | supervisor | 재시작 요청 (내용: resume/new) |

### Supervisor 상태 (`D:/workspace/mcp/logs/`)

| 파일 | 용도 |
|---|---|
| `supervisor.lock` | 단일 인스턴스 보장 (PID + 시작 시각) |
| `supervisor_status.json` | 전체 세션 상태 (PID, origin, status, restart_count) |
| `supervisor.log` | 실행 로그 (최대 500줄 롤링) |
| `hooks.log` | 훅 스크립트 디버그 로그 (최대 500줄 롤링) |
| `relay-stop-debug.log` | relay-stop.py 디버그 로그 (최대 500줄 롤링) |

### 에뮬레이터

| 파일 | 용도 |
|---|---|
| `D:/workspace/emulator_lock.json` | 에뮬레이터 잠금 (project, since) |

## 외부 의존성

| 의존성 | 사용 스크립트 | 용도 |
|---|---|---|
| `httpx` | supervisor.py | 텔레그램 알림 전송 |
| `urllib.request` | relay-tool-use.py, relay-stop.py | 텔레그램 메시지 전송 |
| `adb` | emu-ui.sh, ai-player.py, stability-test.sh | 에뮬레이터 제어 |
| `uiautomator` | emu-ui.sh | UI XML 덤프 |
| `powershell.exe` | supervisor.py, check-session-status.sh | 프로세스 조회, SendKeys, 세션 시작 |
| `tasklist` / `taskkill` | supervisor.py | PID 생존 확인, 프로세스 종료 |
| `claude CLI` | supervisor.py | Claude Code 세션 시작 (`--dangerously-skip-permissions`) |
| Telegram Bot API | supervisor.py, relay 훅 | 알림/중계 전송 |
| Claude 세션 파일 (`C:\Users\kok34\.claude\sessions\*.json`) | supervisor.py, check-session-status.sh | PID-프로젝트 매핑 |

# TeleClaw

**Claude Code 세션을 텔레그램에서 원격 제어하는 슈퍼바이저.**

PC에서 Claude Code로 작업하다가 자리를 비워도, 텔레그램으로 진행 상황을 보고 지시를 내릴 수 있습니다.

## NanoClaw와 뭐가 다른가요?

| | NanoClaw | TeleClaw |
|---|---|---|
| **방식** | 채팅할 때마다 새 에이전트 생성 | **기존 세션에 명령 전달** (컨텍스트 유지) |
| **핵심** | 보안 컨테이너, 멀티채널 | **운영 안정성, 자동 복구, 라이브 모니터링** |
| **비유** | 매번 새 개발자 고용 | 이미 프로젝트 파악한 개발자한테 카톡으로 지시 |

## 주요 기능

- **텔레그램 원격 제어** — 메시지로 Claude Code에 지시, 라이브 스트리밍으로 응답 확인
- **멀티 세션 관리** — 여러 프로젝트를 독립 텔레그램 봇으로 동시 운영
- **자동 복구** — DEAD/STUCK 감지 시 자동 재시작 + auto-resume (3단계 안전장치)
- **워치독 이중 보호** — wrapper(프로세스 레벨) + watchdog(asyncio 레벨)
- **SDK 버퍼 밀림 방지** — N턴 밀림 문제 해결 (Claude SDK 사용자 공통 이슈)
- **6가지 경로별 재시도** — noclient, conn, timeout, error, image_error, rate_limit 각각 맞춤 전략
- **라이브 스트리밍** — 3초 버퍼링 + editMessage로 실시간 응답 업데이트
- **도구 사용 중계** — 어떤 파일 읽고 수정하는지 텔레그램으로 실시간 확인

## 아키텍처

```
텔레그램 (모바일)
    ↓ long poll (25s)
TeleClaw Supervisor (asyncio)
    ├── 봇 폴링 루프 (×N 프로젝트)
    ├── 세션 루프 (×N) — SDK query + 스트리밍 응답
    ├── 건강 체크 루프 (2분 주기)
    ├── flag 감시 루프 (1초)
    └── watchdog 루프 (5분)
    ↓
Claude Code SDK (claude-code-sdk)
    ↓
Claude Code 세션 (프로젝트별 독립)
```

## 설치

### 1. 요구 사항

- Python 3.11+
- [Claude Code](https://claude.ai/claude-code) 설치 및 인증 완료
- 텔레그램 봇 생성 (@BotFather)

### 2. 설치

```bash
git clone https://github.com/YOUR_USERNAME/teleClaw.git
cd teleClaw
pip install -r requirements.txt
```

### 3. 설정

```bash
cp config.example.yaml config.yaml
```

`config.yaml`을 편집하여 실제 값을 입력:

```yaml
chat_id: "YOUR_TELEGRAM_CHAT_ID"

projects:
  MyProject:
    cwd: "/path/to/your/project"
    bot_token: "BOT_TOKEN_FROM_BOTFATHER"
    bot_id: "BOT_ID_NUMBER"
```

### 4. 실행

```bash
# 직접 실행
python -m hub

# 자동 재시작 래퍼 (권장)
python supervisor-wrapper.py
```

## 텔레그램 명령어

| 명령어 | 기능 |
|---|---|
| (일반 메시지) | Claude Code에 지시 전달 |
| `/status` | 전체 세션 상태 (OK/DEAD/STUCK/PAUSED) |
| `/usage` | Claude 사용량 조회 |
| `/restart [name]` | 세션 재시작 (auto-resume 활성) |
| `/reset [name]` | 세션 리셋 (컨텍스트 초기화) |
| `/pause <name>` | 세션 일시정지 |
| `/wakeup [name]` | 일시정지 해제 |
| `/log [N]` | 슈퍼바이저 로그 (기본 20줄) |
| `/sys` | 시스템 정보 (CPU/메모리) |

## 파일 구조

```
teleClaw/
├── hub/                    # 메인 패키지
│   ├── supervisor.py       # Supervisor 클래스 (핵심)
│   ├── telegram_api.py     # 텔레그램 API (동기/비동기)
│   ├── commands.py         # 명령어 핸들러
│   ├── session.py          # SessionState 데이터클래스
│   ├── config.py           # config.yaml 로더
│   ├── process_utils.py    # 크로스 플랫폼 프로세스 유틸
│   ├── usage_fmt.py        # 사용량 포맷 유틸
│   └── logging_utils.py    # 로깅 유틸
├── supervisor-wrapper.py   # 자동 재시작 래퍼
├── relay-stop.py           # Stop 훅 (응답 → 텔레그램)
├── relay-tool-use.py       # PostToolUse 훅 (도구 → 텔레그램)
├── relay_common.py         # 훅 공통 유틸
├── svctl.py                # CLI 도구
├── config.yaml             # 설정 (gitignore)
├── config.example.yaml     # 설정 템플릿
├── requirements.txt        # 의존성
└── LICENSE                 # MIT
```

## 라이선스

MIT License

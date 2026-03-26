# TeleClaw GitHub 배포 계획

## 개요
슈퍼바이저 모듈을 `teleclaw`라는 이름으로 GitHub에 공개 배포한다.
Claude Code 세션을 텔레그램으로 원격 제어하는 데몬.

## 참고 프로젝트
- [NanoClaw](https://github.com/qwibitai/nanoclaw) — Claude Code 에이전트 관리, 스킬 시스템, fork→clone→claude 설치 방식
- [claude-code-telegram](https://github.com/RichardAtCT/claude-code-telegram) — 텔레그램→Claude Code 원격 접근 (2.3K stars)

## TeleClaw 차별점
- **세션 지속성**: 매번 새 query가 아닌 기존 세션 유지 + 컨텍스트 보존
- **멀티 프로젝트**: config.yaml로 N개 프로젝트 동시 관리
- **자동 복구**: DEAD/STUCK 감지 → 3단계 재시작 + watchdog
- **운영 도구**: svctl.py (상태/재시작/로그/사용량)
- **relay 훅**: 도구 사용 + 중간 텍스트 실시간 중계

## 결정 사항
- Docker: 제외 (스켈레톤 상태, 실제 동작 안 함)
- 컨테이너 격리: 불필요 (1인 사용 전제)
- 설치 방식: `git clone → cd teleclaw → claude → /setup` (NanoClaw 스타일)

## 단계

### 1단계: 리포 뼈대
- [ ] 리포 이름/구조 확정
- [ ] `pyproject.toml` 생성
- [ ] `.gitignore` 정리 (민감 정보 제거)
- [ ] LICENSE (MIT 이미 있음)
- [ ] Docker 파일 제거 (Dockerfile, docker-compose.yml, .dockerignore)

### 2단계: README
- [ ] 영문 README (what / why / how)
- [ ] 스크린샷 or GIF (텔레그램 대화 예시)
- [ ] claude-code-telegram과의 차별점 명시

### 3단계: /setup 스킬
- [ ] `.claude/skills/setup/SKILL.md` 작성
- [ ] 봇 토큰 → config.yaml → pip install → 실행까지 자동화

### 4단계: GitHub 배포
- [ ] 리포 생성 (`gbongk/teleclaw`)
- [ ] 첫 커밋 + push
- [ ] 태그/릴리스 (v0.1.0)

### 5단계: 크로스 플랫폼 (Linux 메인 + Windows)
- [ ] 프로세스 관리: `tasklist`/`taskkill`/`powershell` → `psutil`로 통일 (7곳)
- [ ] 인코딩: `cp949` 처리를 `sys.platform == "win32"` 조건부 정리
- [ ] systemd 서비스 템플릿: `teleclaw.service` 생성
- [ ] Windows Task Scheduler: 기존 `Supervisor.xml` 정리
- [ ] CLI 통합: `teleclaw install` → OS 감지 → systemd 또는 schtasks 등록
- [ ] CLI: `teleclaw uninstall`, `teleclaw start/stop/status` 래핑

### 6단계: 추후 개선 (선택)
- [ ] Docker 지원
- [ ] flag 파일 → SQLite 전환
- [ ] 멀티채널 (Discord 등)
- [ ] 기본 보안 (ALLOWED_USERS)
- [ ] 영문화
- [ ] `uv tool install` / `pip install teleclaw` 지원
- [ ] Claude Code Channels 공식 기능과 연동 검토

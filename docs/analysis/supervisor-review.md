# Supervisor 코드 리뷰 (2026-03-18)

DuckDuckGo AI + Gemini 크로스 리뷰 + Claude 종합

## 🔴 실제 위험도 높음 (양쪽 모두 동의)

### 1. _send_wait_after_resume 무한 재시작 ✅ 수정됨
- new 모드도 실패하면 `start_session`이 또 스레드 생성 → 스레드 기하급수적 누적
- `restart_history` 체크가 이 함수 안에는 없음
- **수정**: `restart_session`으로 위임하여 restart_history 체크 포함. `resume_failed_at` 설정으로 다음 재시작 시 new 모드

### 2. taskkill 후 즉시 start → 리소스 충돌 ✅ 수정됨
- `taskkill`은 비동기적. 이전 프로세스가 파일/포트 점유 중인데 새 세션 시작
- **수정**: `_stop_session_locked` 내에서 taskkill 후 PID 소멸 대기 루프 (최대 10초, 0.5초 간격)

### 3. heartbeat 파일 읽기 실패 → 오판 ✅ 수정됨
- 쓰는 중에 읽으면 `PermissionError` → `None` 반환 → STALE/STUCK 오판 → 멀쩡한 세션 강제 재시작
- Gemini 평가: "가장 치명적"
- **수정**: 0.1초 간격 3회 재시도 + `FileNotFoundError`는 즉시 None + 모두 실패 시 이전 캐시값(`state.last_hb_age`) 반환

### 4. 중복 실행 (Double Start) ✅ 수정됨
- `_check_restart_requests`(1초 폴링)와 `health_check_all`(120초)이 동시에 같은 세션 재시작 → 프로세스 2개
- **수정**: `state.restarting` 플래그 도입. restart_session, _check_restart_requests 진입 시 가드. try/finally로 항상 복원
- **참고**: 메인 루프가 단일 스레드이므로 이 둘의 직접 경합 확률은 낮음. 단, `_send_wait_after_resume`는 별도 스레드이므로 여기서의 재시작은 경합 가능

## 🟡 중간 위험도

### 5. 세션 관리 락 불일치 ✅ 수정됨
- `start_session`/`stop_session` 자체는 lock 없이 호출 가능
- **수정**: `threading.RLock()` + `_start_session_locked`/`_stop_session_locked` 분리. 외부 호출은 락, 내부는 _locked 직접 호출

### 6. acquire_lock 원자성 — 미수정 (위험도 낮음)
- `exists` → `remove` → `open` 사이에 다른 인스턴스 개입 가능
- 실제로는 Task Scheduler 단일 실행이라 위험도 낮음
- 개선 시: `O_CREAT|O_EXCL` 실패 시에만 stale 체크하는 순서로 변경

### 7. resume_failed_at 미갱신 ✅ 수정됨
- **수정**: `restart_session` 실패 시 + `_send_wait_after_resume` 실패 시 `resume_failed_at` 설정

## 🟢 낮은 위험도 — 미수정

### 8. _log_line_count 스레드 안전성
- global 변수를 lock 밖에서 접근하지만, 카운트 꼬여도 로그 truncate 타이밍만 약간 어긋남

### 9. SendKeys 비결정성
- 포커스가 다른 창에 있으면 엉뚱한 곳에 입력
- 무인(headless) 환경에서는 영향 적음

### 10. 30분 STUCK 판정
- 긴 작업 중일 수 있지만, `pending` 체크와 결합되어 있어 실제 오판 확률 낮음
- CPU 점유율도 같이 보면 정확도 향상 (Gemini 제안)

## 추가 제안 (Gemini) — 미적용

- `psutil` 라이브러리 도입으로 프로세스 관리 정확도 향상
- 프로세스 감시를 `proc.poll()` 대신 `psutil`로 자식 프로세스 트리까지 관리

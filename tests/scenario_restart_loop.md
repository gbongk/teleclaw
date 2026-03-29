# 재시작 무한 루프 방지 테스트

2026-03-22 슈퍼바이저/세션 재시작 시 auto-resume 무한 루프 방지.

## 구조

### 안전장치
1. `_fresh_start` 플래그 — 슈퍼바이저 시작 시 auto-resume 안 함
2. `resume_count >= 2` — 연속 재개 2회 초과 시 중단 + 알림
3. `was_busy_before_restart` — 대기 중이던 세션은 재개 안 함
4. `session_id` 없으면 재개 안 함 (맥락 유실)
5. `mode == "new"` — 리셋 모드는 재개 안 함

### 동작 매트릭스

| 시나리오 | fresh_start | mode | was_busy | session_id | auto-resume |
|---|---|---|---|---|---|
| 슈퍼바이저 시작 | true | - | - | - | **안 됨** (대기 모드) |
| 세션 재시작 (resume) — busy → 복구 | false | resume | true | 있음 | **됨** |
| 세션 재시작 (resume) — idle | false | resume | false | 있음 | **안 됨** |
| 세션 재시작 — session_id 없음 | false | resume | true | 없음 | **안 됨** |
| 세션 리셋 (new) | false | new | - | - | **안 됨** |
| 재개 2회 초과 | false | resume | true | 있음 | **중단 + 알림** |

---

## 1. 슈퍼바이저 시작 — 모든 세션 대기 모드
- [입력] 슈퍼바이저 프로세스 시작 (restart_request_supervisor.flag)
- [확인] `_fresh_start = True` → `_restart_session`에서 auto-resume 스킵
- [확인] 로그: "{name}: 연결 완료 — 대기 모드"
- [기대] 모든 세션 auto-resume 안 됨

## 2. 세션 개별 재시작 (resume) — busy → 정상 재개
- [입력] Crossword가 busy 상태에서 restart_request_Crossword.flag(resume)
- [확인] was_busy_before_restart=True, session_id 존재, _fresh_start=False
- [기대] auto-resume 트리거 → AI에게 판단 위임

## 3. 세션 개별 재시작 (resume) — idle → 재개 안 함
- [입력] NemoNemo가 idle 상태에서 restart_request_NemoNemo.flag(resume)
- [확인] was_busy_before_restart=False
- [기대] "재시작 전 대기 상태 → 자동 재개 스킵" 로그

## 4. 세션 리셋 (new) — 재개 안 함
- [입력] restart_request_Converter.flag에 "new" 작성
- [확인] mode == "new" → auto-resume 블록 스킵
- [기대] 새 대화 시작, 재개 없음

## 5. session_id 유실 — 재개 안 함
- [입력] session_ids.json에서 해당 세션 삭제 후 세션 재시작
- [확인] session_id 없음 → `_should_auto_resume` False
- [기대] "session_id 없음 (맥락 유실) → 자동 재개 스킵" 로그

## 6. resume_count 2회 초과 — 중단 + 알림
- [입력] 세션이 재개 → 재시작 → 재개 → 재시작 → 재개 시도 (3회째)
- [확인] resume_count >= 2 → 스킵
- [기대] "자동 재개 2회 초과 → 중단" 로그 + 텔레그램 알림

## 7. STUCK 감지 → 정상 재개
- [입력] health_check에서 30분 STUCK 감지 → _restart_session 호출
- [확인] was_busy_before_restart=True (STUCK은 busy 강제), _fresh_start=False
- [기대] auto-resume 정상 트리거

## 8. 정상 완료 시 resume_count 리셋
- [입력] 자동 재개 후 AI가 정상 응답 완료
- [확인] resume_count가 0으로 리셋
- [기대] 다음 재시작 시 카운트 초기화

## 9. 사용자 메시지 시 resume_count 리셋
- [입력] 자동 재개 카운트 1 상태에서 사용자가 텔레그램 메시지 전송
- [확인] is_auto_resume=False → resume_count=0
- [기대] 사용자 메시지가 카운트 초기화

## 10. query 초기화 타임아웃 — resume 모드로 재시작
- [입력] query() 초기화 10초 타임아웃 발생
- [확인] mode="resume", force=True로 _restart_session 호출
- [기대] 기존 컨텍스트 유지한 채 재시작 (reset 아님)

## 11. 이미지 누적 에러 — reset 예외 (유일한 자동 reset)
- [입력] "dimension limit" 또는 "many-image" 에러 발생
- [확인] mode="reset", force=True로 _restart_session 호출
- [기대] 컨텍스트 초기화 (resume으로는 해결 불가)

---
## 테스트 기록
- 2026-03-23: reset 기본값 변경 반영 — query 타임아웃 resume, 이미지 에러만 reset 예외
- 2026-03-22: 문서 작성 (구조 재설계 반영)

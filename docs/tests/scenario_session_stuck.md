# 세션 멈춤(Stuck) 시나리오 테스트

2026-03-21 NemoNemo 세션이 메시지 수신 후 처리하지 못하는 문제 기반.

## 증상
- 메시지 수신 로그는 찍힘
- "메시지 처리 시작" 로그가 안 찍힘
- hub_status에서 busy=false, query_count=0
- SDK 세션 연결은 정상 (connected=true)

## 1. 리셋 후 메시지 처리
- [입력] `/reset NemoNemo` → 리셋 완료 대기 → 새 메시지 전송
- [확인] "메시지 처리 시작" 로그 찍힘
- [기대] 메시지가 큐에서 빠져서 정상 처리

## 2. resume 후 _session_loop 시작 확인
- [입력] `/restart NemoNemo` (resume 모드)
- [확인] "연결 완료" 로그 후 _session_loop이 시작됨
- [기대] message_queue.get() 대기 상태 진입 (60초 타임아웃 루프)

## 3. auto_resume 스킵 후 일반 메시지 처리
- [입력] resume 모드 + was_busy=False → auto_resume 스킵
- [입력] 사용자가 새 메시지 전송
- [확인] auto_resume 스킵 후에도 일반 메시지는 정상 처리
- [기대] 큐에서 메시지 꺼내서 처리

## 4. _session_loop 재시작 누락
- [확인] _restart_session 후 _session_loop 태스크가 재생성되는지
- [기대] _connect_session 성공 후 _session_loop asyncio.Task 생성

## 5. message_queue에 메시지 쌓임 확인
- [입력] 세션 멈춤 상태에서 메시지 2개 전송
- [확인] message_queue.qsize() == 2
- [입력] 세션 재시작
- [기대] 큐에 쌓인 메시지가 순차 처리됨

## 6. STUCK 감지 (30분 타임아웃)
- [입력] busy=True 상태에서 30분 경과
- [확인] health_check에서 STUCK 상태 감지
- [기대] 자동 재시작 트리거

## 7. busy=False + 미처리 메시지 (현재 미감지)
- [입력] busy=False인데 큐에 메시지가 쌓여있는 경우
- [확인] 현재 health_check에서 이 상태를 감지하는지
- [기대] 새로운 감지 조건 필요: "connected + !busy + queue.qsize > 0 + 5분 경과 → STUCK"

## 8. SDK query 후 무응답
- [입력] client.query(text) 호출 후 receive_messages에서 무한 대기
- [확인] 30분 후 STUCK 감지 → 재시작
- [기대] query 자체에도 타임아웃 적용

## 9. _session_loop 예외 발생 시 복구
- [입력] _session_loop 내부에서 예외 발생
- [확인] 예외가 로깅되고 루프가 재시작되는지
- [기대] 단일 예외가 전체 세션을 죽이지 않음

## 10. 연결 직후 메시지 전송 타이밍
- [입력] SDK 연결 완료 직후 (1초 이내) 사용자 메시지 수신
- [확인] _session_loop이 아직 시작 안 된 상태에서 큐에 들어간 메시지
- [기대] _session_loop 시작 후 큐에서 꺼내서 처리

## 근본 원인 조사 (코드 확인 필요)

### 가설 1: _session_loop 태스크 미생성
- _restart_session에서 _connect_session 호출 후 _session_loop 재시작 누락

### 가설 2: _session_loop에서 auto_resume 처리 후 루프 진입 실패
- _should_auto_resume이 False 반환 → 정상
- 하지만 이후 while 루프에서 message_queue.get() 호출이 안 되는 상태

### 가설 3: asyncio 이벤트 루프 문제
- disconnect 에러 "cancel scope in different task" 후 이벤트 루프 꼬임

---
## 테스트 기록
- 2026-03-21: NemoNemo 세션 멈춤 발생 (19:27~). reset으로 복구.
  - 증상: 메시지 수신됨, 처리 안 됨, busy=false, query_count=0
  - 직전: resume 모드 재시작 + "disconnect 에러: cancel scope in different task"

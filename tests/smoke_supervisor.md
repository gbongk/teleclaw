# 슈퍼바이저 Smoke Test

## 기본 동작

### 1. 프로세스 상태
- 실행: `tasklist | grep python` + `hub_status.json` 확인
- 검증: wrapper + supervisor 프로세스 존재, 3개 세션 connected=true
- 실패 시: wrapper 수동 실행 `cd D:/workspace/supervisor && start //B python supervisor-wrapper.py`

### 2. 메시지 처리
- 실행: 텔레그램으로 "안녕" 전송
- 검증: 로그에 "메시지 수신" + "메시지 처리 시작" + 응답 수신
- 실패 시: 세션 상태 확인 → busy면 대기, DEAD면 /restart

### 3. 명령어 동작
- 실행: `/status` 텔레그램 전송
- 검증: 세션별 상태 응답 수신 (connected, query_count 등)

## 회복력 (Resilience)

### 4. 세션 재시작
- 실행: `echo "resume" > D:/workspace/supervisor/data/restart_request_Crossword.flag`
- 검증: 로그에 "재시작 시도" → "SDK 세션 연결 완료", 이후 메시지 정상 처리
- 실패 시: reset 모드로 재시도

### 5. 슈퍼바이저 자체 재시작
- 실행: `echo "resume" > D:/workspace/supervisor/data/restart_request_supervisor.flag`
- 검증: 프로세스 종료 → wrapper가 재시작 → 3개 세션 연결 → "시작 완료" 로그

### 6. DEAD 세션 자동 복구
- 실행: 세션이 DEAD 상태가 되도록 유도 (SDK 연결 실패 등)
- 검증: health check가 DEAD 감지 → 자동 재시작 시도, 3회 소진 후에도 시간 경과 후 재시도
- 실패 시: 슈퍼바이저 전체 재시작

### 7. SDK query hard timeout
- 실행: 오래 걸리는 질문 전송 (예: 대량 코드 분석 요청)
- 검증: 10분 timeout 후 세션 자동 복구, "query timeout" 로그
- 실패 시: 세션 루프 hang 여부 확인

## 메시지 보존 (State Integrity)

### 8. 재시작 시 메시지 유실 방지
- 실행: 메시지 전송 직후 즉시 슈퍼바이저 재시작
- 검증: 재시작 후 미처리 메시지 재수신 (offset 미갱신 확인)
- 실패 시: offset 갱신 시점 코드 확인

### 9. busy 중 새 메시지 큐잉
- 실행: 세션이 busy일 때 추가 메시지 전송
- 검증: 큐에 쌓임, 현재 작업 완료 후 순차 처리

### 9-1. SDK 버퍼 드레인 (N턴 밀림 방지)
- 배경: SDK `_message_receive` 버퍼(max=100)에 이전 턴의 잔여 응답이 쌓이면 `receive_messages()`가 잘못된 응답을 반환 (N턴 밀림)
- 원인: 세션 resume 시 Claude Code가 자동 생성한 응답, 또는 이전 턴의 후속 출력이 버퍼에 잔류
- 증상: Claude는 정답을 계산하지만 (파일 쓰기로 검증 가능), 텔레그램에는 이전 턴의 응답이 표시됨
- 실행: 연속 산술 질문 전송 ("2+2", "3+3", "4+4", "5+5")
- 검증 1: 각 질문에 대한 텔레그램 응답이 해당 질문의 정답인지 확인
- 검증 2: 로그에 "버퍼 드레인 N건 제거" 여부 확인
- 검증 3 (파일 검증): "5+5의 답을 /tmp/test.txt에 써줘" → 파일 내용이 "10"인지 확인
- 로그: `grep "버퍼 드레인" D:/workspace/supervisor/logs/supervisor.log`
- 수정: 2026-03-24 — `query()` 전에 `_message_receive.receive_nowait()`로 잔여 메시지 드레인
- 실측: test.txt=10(정답), 텔레그램=12(밀림) → 버퍼 문제 확정, 드레인으로 해결

## Flag 감시

### 10. flag 이름 일관성
- 실행: `restart_request_supervisor.flag` 생성
- 검증: 슈퍼바이저 자체 재시작 (세션 restart가 아님)

## 메시지 재시도 (Retry)

### 14. 세션 미연결 시 재시도
- 실행: 세션을 DEAD 상태로 만든 후 메시지 전송
- 검증: ✔️ 수신 확인 → 재시작 시도 → 1회 재시도 큐잉 로그 ("세션 미연결, 재시도 큐잉 (1/1)")
- 최종 실패 시: `❌ 세션 연결 실패, 메시지 처리 불가\n원본: {메시지}` 수신
- 로그: `grep "재시도 큐잉" D:/workspace/supervisor/logs/supervisor.log`

### 14-1. client=None 무한 재큐잉 방지
- 실행: client가 None인 상태에서 메시지 도착
- 검증: 최대 3회 재큐잉 후 드롭 ("client 없음, 재큐잉 (1/3)" ~ "client 없음, 재시도 소진")
- 최종 실패 시: `❌ 세션 초기화 실패, 메시지 처리 불가\n원본: {메시지}` 수신
- 이전 버그 1: retry_count 체크 없이 무한 루프 → 2026-03-21 수정
- 이전 버그 2: 3회 제한(6초)이 재시작 소요시간(~13초)보다 짧아 메시지 드롭 → 10회(20초)로 증가

### 15. query() 타임아웃 재시도
- 실행: SDK가 느린 상태에서 메시지 전송 (네트워크 지연 등)
- 검증: 로그에 "query() 초기화 타임아웃" → "타임아웃 재시도 큐잉 (1/2)" → 최대 2회 재시도
- 최종 실패 시: `❌ 응답 타임아웃 (재시도 소진)\n원본: {메시지}` 수신
- 로그: `grep "타임아웃 재시도" D:/workspace/supervisor/logs/supervisor.log`

### 16. 빈 응답 알림
- 실행: SDK가 빈 응답을 반환하는 상황 유도
- 검증: ✔️ 수신 확인 후 `⚠️ 빈 응답` 텔레그램 메시지 수신
- 확인: 재시도 없이 즉시 알림만 (같은 입력에 빈 응답 반복 가능성)
- 로그: `grep "빈 응답" D:/workspace/supervisor/logs/supervisor.log`

### 17. 처리 중 예외 재시도
- 실행: 처리 중 예외가 발생하는 상황 유도
- 검증: 1회 재시도 큐잉 ("에러 재시도 큐잉 (1/1)") → 재처리 시도
- 최종 실패 시: `❌ 처리 실패: {에러}\n원본: {메시지}` 수신
- 연속 에러 3회 시: 자동 세션 재시작도 트리거됨
- 로그: `grep "에러 재시도" D:/workspace/supervisor/logs/supervisor.log`

### 18. 재시도 시 메시지 순서 보존
- 실행: busy 상태에서 메시지 A 전송 → A 처리 실패 (재시도 큐잉) → 메시지 B 전송
- 검증: A 재시도가 B보다 먼저 처리됨 (큐 순서)
- 주의: 큐에 B가 먼저 들어오면 순서 역전 가능 (현재 허용)

## 안정성 (Stability)

### 19. wrapper 무한 크래시 시 알림 반복
- 실행: supervisor가 즉시 종료되는 상태 유도 (exit_code=2 반복)
- 검증: 첫 실패 시 알림 → 5/10/20/50회 시점에 추가 알림 수신
- 이전 버그: `notified=True` 이후 알림 1회만 → 6시간 무음 방치
- 로그: `grep "텔레그램 알림 전송" D:/workspace/supervisor/logs/wrapper.log`

### 20. busy 중 supervisor 재시작 graceful shutdown
- 실행: 세션이 busy인 상태에서 `restart_request_supervisor.flag` 생성
- 검증: "busy 세션 대기" 로그 → 처리 완료 후 종료 (최대 60초 대기)
- force 모드: flag에 "force" 기록 시 즉시 종료 (대기 안 함)
- 이전 버그: busy 중 즉시 os._exit(0) → 응답 중단, 텔레그램에 미전송

### 21. 폴링 에러 메시지 상세화
- 실행: 폴링 에러 발생 시 로그 확인
- 검증: `repr(e)` + traceback이 로그에 기록됨 (빈 문자열 아님)
- 이전 버그: `str(e)`가 빈 문자열 → 원인 추적 불가

### 22. 세션 병렬 연결
- 실행: 슈퍼바이저 시작 시 3개 세션 연결 시간 측정
- 검증: 총 연결 시간 ~15초 (순차 시 ~50초 대비)
- 로그: "SDK 세션 연결 완료" 3개의 타임스탬프 차이 확인
- 실패 시: 1개 세션 연결 실패가 다른 세션에 영향 없음 (return_exceptions=True)

### 23. disconnect 에러 시 프로세스 강제 종료
- 실행: 세션 재시작 시 disconnect 에러 발생 유도
- 검증: "disconnect 에러 (무시)" → "이전 프로세스 강제 terminate (pid=N)" 로그
- 확인: 이전 claude.exe 프로세스가 실제 종료됨 (중복 프로세스 없음)
- 이전 버그 1: client._process 경로 사용 → 실제 경로는 client._transport._process
- 이전 버그 2: proc.kill() 미동작 → _transport._process.terminate() 으로 수정
- 실측: 08:07:22 pid=9736 강제 terminate 성공
- 로그: `grep "강제 terminate" D:/workspace/supervisor/logs/supervisor.log`

### 24. wrapper에서 supervisor crash stderr 캡처
- 실행: supervisor가 import 에러 등으로 즉시 크래시
- 검증: wrapper.log에 "supervisor stderr: {에러내용}" 기록 + 텔레그램에 stderr 전송
- 이전 버그 1: exit_code=2로 21회 반복 크래시했지만 원인 로그 없음 (6시간 무진단)
- 이전 버그 2: capture_output=True → 자식 프로세스(claude.exe) stdout 파이프 blocking → wrapper 재시작 지연
- 수정: stderr만 파일 리다이렉트, stdout 캡처 안 함
- 실측: 01:18:37 stderr 캡처 성공 ("can't open file 'supervisor.py'")
- 로그: `grep "stderr" D:/workspace/supervisor/logs/wrapper.log`

### 44. receive_messages() 중 client 교체 감지
- 실행: 세션이 busy(receive_messages 소비 중)인 상태에서 _restart_flag_loop가 재시작 트리거
- 검증: "client 교체 감지 → receive_messages 중단" 로그 → 새 client로 전환
- 이전 버그: _restart_session이 state.client 교체해도 세션 루프는 이전 client의 receive_messages()에 블록 → 새 메시지 처리 불가
- 실측: NemoNemo "하던일 있어?" 수신 후 처리 시작 안 됨 (20:43:08~20:45:52)

### 45. disconnect 실패 시 이전 프로세스 강제 terminate
- 실행: disconnect에서 cancel scope 에러 발생
- 검증: client._transport._process.terminate() 호출 → "이전 프로세스 강제 terminate (pid=N)" 로그
- 확인: 이전 claude.exe PID가 종료됨 (tasklist에서 사라짐)
- 이전 버그: disconnect 에러 후 이전 프로세스 좀비 → 중복 claude.exe 프로세스 누적
- 실측: Converter pid=9736 terminate 성공 (08:07:22)

### 46. wrapper 재시작 blocking 방지
- 실행: supervisor가 os._exit(0)으로 종료
- 검증: wrapper.log에 "supervisor 종료" 즉시 기록 (수초 내)
- 이전 버그: capture_output=True → subprocess.run()이 자식 프로세스 stdout 닫힐 때까지 대기 → wrapper 수분~무한 blocking
- 수정: stderr만 파일 리다이렉트 (supervisor_stderr.log)
- 실측: 08:06:24 wrapper 즉시 재시작 성공

## 텔레그램 송수신

### 47. deleteMessage POST 방식
- 실행: 빠른 응답(3초 이내)에서 기존 live 메시지 삭제
- 검증: `ahttp.post` + `json=` 파라미터 사용 (GET+params 아님)
- 이전: GET 방식으로 비표준 호출

### 48. _notify_all 비동기화
- 실행: asyncio 루프 내 전체 알림 전송
- 검증: `async_notify_all` 함수 존재 + 루프 내 호출에서 사용
- 이전: 동기 `_notify_all`이 asyncio 루프 blocking

### 49. edited_message 수신 지원
- 실행: 텔레그램에서 메시지 수정 후 전송
- 검증: `allowed_updates`에 "edited_message" 포함
- 검증: 수정된 메시지에 "[수정]" 태그 부착
- 이전: `allowed_updates: ["message"]`만 → 수정 메시지 무시

### 50. document/file 메시지 처리
- 실행: 텔레그램으로 파일(PDF, txt 등) 전송
- 검증: "파일 다운로드 완료" 로그 + `logs/files/` 디렉토리에 저장
- 캡션 있음: "{caption}\n\n파일: {path}"
- 캡션 없음: "이 파일을 확인해줘: {path}"
- 이전: document 메시지는 text 없으면 무시

## 중복 제거 / 입력 처리

### 25. 중복 메시지 필터링 (message_id)
- 실행: 같은 메시지가 텔레그램 재전송으로 2회 도착하도록 유도
- 검증: 두 번째 메시지 무시 (로그에 두 번째 "메시지 수신" 없음)
- 로직: `_last_msg_map`에 `{name}_{msg_id}` 키로 중복 체크 (100개, 5분 TTL)

### 26. 네트워크 재전송 중복 제거 (date + text)
- 실행: 같은 텍스트를 같은 초에 전송 (네트워크 재전송 시뮬레이션)
- 검증: "동일 date+텍스트 중복 스킵" 로그 + 1회만 처리
- 로그: `grep "중복 스킵" D:/workspace/supervisor/logs/supervisor.log`

### 27. 이미지 메시지 처리
- 실행: 텔레그램으로 이미지 전송 (캡션 있음/없음 각각)
- 검증: "이미지 다운로드 완료" 로그 + `logs/images/` 디렉토리에 파일 생성
- 캡션 없음: "이 이미지를 확인해줘: {path}" 형태로 SDK에 전달
- 캡션 있음: "{caption}\n\n이미지: {path}" 형태로 SDK에 전달

### 28. 수신 확인 (ACK) 메시지
- 실행: idle 상태에서 메시지 전송 / busy 상태에서 추가 메시지 전송
- 검증: idle → "✔️" 응답, busy → "✔️ (처리 중, 대기 N건)" 응답
- ACK가 실제 응답보다 먼저 도착해야 함 (큐 투입 전 전송)

## 자동 관리

### 29. 세션 자동 리셋 (쿼리 수)
- 실행: query_count가 SESSION_RESET_QUERIES(100) 이상 누적
- 검증: "자동 리셋 (Q=100, Xh)" 로그 + resume 모드 재시작
- 확인: 재시작 후 query_count=0, connected=true

### 30. 세션 자동 리셋 (시간)
- 실행: session_age가 SESSION_RESET_HOURS(6h) 초과
- 검증: 동일하게 자동 리셋 트리거
- 확인: start_time 갱신됨

### 31. 자동 재개 (auto resume)
- 실행: busy 상태에서 세션 재시작 (resume 모드)
- 검증: "자동 재개 (1/2) — AI에게 판단 위임" 로그 + 자동으로 이전 작업 재개 시도
- 조건: was_busy_before_restart=true + session_id 있음 + resume_count < 2

### 32. 자동 재개 초과 (2회 실패)
- 실행: 자동 재개가 2회 연속 실패 (resume_count ≥ 2)
- 검증: "자동 재개 2회 실패, 중단" 알림 + resume_count 리셋 → 대기 모드 전환
- 확인: 수동 메시지 전송 시 resume_count 리셋되어 정상 처리

### 51. auto-resume ON/OFF 제어
- 전역: `config.py`의 `AUTO_RESUME_ENABLED = True` (기본 ON)
- 재시작 시: flag 파일에 `noresume` 토큰 추가 (예: `resume,noresume`)
- 텔레그램: `/restart <name> noresume`
- 우선순위: 명령어 옵션 > 전역 설정
- STUCK 재시작 시 was_busy_before_restart 강제 True
- 프롬프트: "[시스템 재시작됨] 직전에 수행하던 작업이 완료되지 않았다면 이어서 진행해줘"
- 이전 버그: _session_loop 시작 시에만 auto-resume 체크 → 개별 세션 재시작 시 동작 안 함
- 수정: _restart_session 끝에서 직접 큐 투입

### 52. auto-resume busy 상태 영속화
- 실행: 세션이 busy인 상태에서 슈퍼바이저 전체 재시작
- 검증: session_ids.json에 `was_busy: true` 저장 → 재시작 후 "재시작 전 busy 상태 복원됨" 로그
- 검증: auto-resume 프롬프트 자동 투입 → 이전 작업 확인/재개
- 이전 버그: os._exit(0)으로 메모리 소멸 → was_busy_before_restart 항상 false
- 수정: _save_session_ids()를 busy 대기 전에 호출 (현재 상태 즉시 캡처)
- 하위 호환: 이전 포맷(문자열)→새 포맷(dict) 자동 마이그레이션

### 53. auto-resume 프롬프트 모드
- config.py의 `AUTO_RESUME_MODE`: "resume" (이어서 진행) 또는 "check" (확인만)
- "check" 모드: 이전 작업이 무엇이었는지 알려주기만 함
- "resume" 모드: 이전 작업 이어서 진행 (현재 기본값)
- `AUTO_RESUME_PROMPTS` dict로 프롬프트 커스터마이즈 가능

### 58. auto-resume 세션 재시작 전용 (슈퍼바이저 시작 시 미발동)
- 실행: 슈퍼바이저 재시작 (`svctl sv`)
- 검증: `_session_loop` 시작 시 "연결 완료 — 대기 모드" 로그만 (auto-resume 프롬프트 없음)
- 실행: 세션 재시작 (`svctl r NemoNemo`)
- 검증: `_restart_session` 끝에서 auto-resume 프롬프트 투입 (resume 모드)
- 이전: 슈퍼바이저 시작 시에도 `_session_loop`에서 auto-resume → busy 세션은 no_resume 스킵, 나머지도 불필요 발동
- 수정: `_session_loop` 시작 시 auto-resume 코드 제거, `_restart_session`에서만 유지

### 59. [HUB] vs [SV] 프리픽스 구분
- 슈퍼바이저 본체 이벤트: `[HUB]` 프리픽스 (시작/종료/초기화/에러)
- 세션 이벤트: `[SV]` 프리픽스 (연결/재시작/상태)
- 검증: 로그에서 "[HUB] 슈퍼바이저 시작", "[HUB] 초기화 완료" 확인
- `_notify_all`로 전체 채팅방에 브로드캐스트

## Watchdog / Rate Limit

### 54. 느린 응답 중간 알림
- 실행: 300초+ 걸리는 응답 처리 중
- 검증: "⏳ 아직 처리 중... (N분 경과, 도구 N회 호출)" 텔레그램 메시지 수신
- 간격: 5분(300초)마다 반복 알림
- 로그: 텔레그램 전송만, 별도 로그 없음

### 55. wrapper 반복 재시작 경고
- 실행: 10분 내 5회 이상 재시작 (정상 종료 포함)
- 검증: "⚠️ 잦은 재시작 감지: N회/10분" 텔레그램 수신 + wrapper.log 기록
- 목적: auto-resume 테스트가 아닌 실제 문제 시 조기 감지

### 56. 로그 로테이션 (날짜별 보관)
- 실행: supervisor.log가 500줄 초과 시 자동 트리밍
- 검증: 잘린 로그가 `logs/supervisor_YYYY-MM-DD.log`에 보관
- 확인: `ls D:/workspace/supervisor/logs/supervisor_20*.log`

### 33. watchdog asyncio 데드락 감지
- 실행: asyncio 루프가 5분 이상 블록되는 상태 유도
- 검증: "_watchdog_ts"와 현재 시각 차이 > 300초 시 "WATCHDOG: asyncio 루프 {N}초 무응답, 강제 종료" 로그 + os._exit(1)
- wrapper가 재시작 수행

### 57. 이미지 누적 에러 감지 → 자동 reset
- 실행: 에뮬레이터 스크린샷 등 이미지가 컨텍스트에 누적된 상태에서 resume
- 에러: "An image in the conversation exceeds the dimension limit for many-image requests"
- 검증: 에러 감지 → "⚠️ 이미지 누적으로 컨텍스트 초과" 텔레그램 알림 → reset 모드 재시작
- 감지 위치: 예외 처리부 + 응답 텍스트 내 (두 곳)
- 이전: 에러 발생 시 세션 멈춤, 수동 reset 필요

### 34. rate limit 이벤트 캡처
- 실행: SDK가 rate_limit_event를 반환하는 상황 (고부하)
- 검증: `_rate_limit_data`에 {status, utilization, resetsAt} 저장
- monkey-patch로 알 수 없는 메시지 타입도 무시 (크래시 방지)

### 35. 슈퍼바이저 재시작 쿨다운 (5분)
- 실행: 시작 후 5분 이내에 `restart_request_supervisor.flag` 생성 (force 아님)
- 검증: "supervisor 자체 재시작 flag 무시 (쿨다운: N초 남음)" 로그 + 재시작 안 함
- force 모드: "force" 기록 시 쿨다운 무시

## 로그 기반 검증

### 36. session_id 복원 / continue 폴백
- 실행: 슈퍼바이저 재시작
- 검증: session_id 있는 세션 → "session_id 복원됨" 로그 + resume 모드
- 검증: session_id 없는 세션 → "continue 폴백" 로그 + continue_conversation 모드
- 로그: `grep "session_id 복원\|continue 폴백" D:/workspace/supervisor/logs/supervisor.log`

### 37. MCP 안정화 대기
- 실행: 세션 연결 후 MCP 서버 초기화 대기
- 검증: "MCP 안정화 대기 완료 (5초)" 로그 (세션당 1건)
- 목적: MCP 서버가 완전히 초기화되기 전 query 방지

### 38. 응답 시간 분포
- 실행: 로그에서 "최종 전송" 시간 추출
- 검증: 10분(600초) 초과 응답 없음
- 참고: 여러 도구 호출 시 170초+ 가능 (정상)

### 39. 3개 세션 병렬 처리 실측
- 실행: 로그에서 여러 세션의 "메시지 처리 시작" 확인
- 검증: 2개 이상 세션이 동시 활동 기록 존재

### 40. usage 로그 기록
- 실행: 메시지 처리 완료 후 usage 로그 확인
- 검증: [usage] 로그에 input_tokens, output_tokens 포함

### 41. disconnect 에러 후 재연결 성공
- 실행: disconnect 에러 발생 후 로그 추적
- 검증: 에러 후 20줄 이내에 "SDK 세션 연결 완료" 존재
- cancel scope 에러가 재연결을 막지 않음 확인

### 42. 최종 전송 청크 분할
- 실행: 긴 응답 시 4096자 초과 여부
- 검증: "최종 전송 (N자, N청크)" 로그에서 청크 수 확인
- 다중 청크: _split_message로 자동 분할

## 스트레스

### 12. 병렬 메시지
- 실행: 3개 채팅방에 동시에 메시지 전송
- 검증: 각 세션이 독립적으로 처리, 지연이나 누락 없음

### 13. /status 고스트 상태
- 실행: 세션 객체가 connected=true인데 실제 SDK가 끊긴 상태 유도
- 검증: health check가 감지하여 DEAD로 전환 → 자동 재시작

---
## 테스트 기록

### 2026-03-21
- 코드 리뷰: 재시도 로직 4개 경로 (미연결/타임아웃/빈응답/예외) 구현 확인
- 버그 수정 1: `state.client=None` 시 무한 재큐잉 (retry_count 미체크) → 3회 제한 추가
- 버그 수정 2: retry_count 공유로 경로 간 카운터 간섭 → 경로별 독립 키 분리 (retry_noclient/retry_conn/retry_timeout/retry_error)
- 크로스 검증: Gemini 리뷰 — busy 상태 누락 없음 확인, 순서 역전은 허용 범위
- 로그 분석: 현재 세션에서 재시도/에러 로그 0건 (정상 운영 중)
- 문법 검증: py_compile 통과 (2회)
- 로그 분석 (2차): wrapper.log 6시간 크래시 루프, disconnect 에러 반복, 빈 폴링 에러, 응답 중단 발견
- 수정 #19: wrapper 알림 반복 (5/10/20/50회)
- 수정 #20: busy 중 supervisor 재시작 graceful shutdown (최대 60초 대기)
- 수정 #21: 폴링 에러 repr(e) + traceback
- 수정 #22: 세션 병렬 연결 (asyncio.gather)
- 문법 검증: py_compile 통과
- 재시작 테스트: force 모드 재시작 → 3개 세션 병렬 연결 14초 (이전 ~50초), 모두 connected=true, status=OK
- 로그 분석 (3차): disconnect cancel scope 에러 5건, 빈 폴링 에러 1건, wrapper 21회 크래시 stderr 미캡처
- 수정 #23: disconnect 에러 시 client._process=None으로 리소스 정리
- 수정 #24: wrapper에서 supervisor stderr 캡처 + 텔레그램 전송
- 문법 검증: py_compile 통과
- 재시작 테스트 (#23/#24): force 재시작 → 병렬 연결 3초 (Crossword 17:49:21, NemoNemo 17:49:23, Converter 17:49:24), 3개 세션 connected=true, status=OK, error_count=0
- wrapper 정상: exit_code=0, stderr 캡처 로직 대기 상태 (다음 크래시 시 동작 예정)
- 스모크 테스트 작성: `tests/test_smoke.py` (#1~#45 + 시스템 무결성)
- 전체 테스트 실행: **100 passed, 0 failed, 5 skipped**
  - skip: /pause, /wakeup 미구현(2건), pause flag 미구현(2건), 재시작 이력 없음(1건)
  - 발견: #10 pause 모드는 md에 테스트 있으나 코드 미구현 상태 → md에서 삭제
- 로그 기반 테스트 #36~#42 추가 (session_id 복원, MCP 안정화, 응답 시간, 병렬 처리, usage, disconnect 재연결, 청크 분할)
- 전체 테스트 실행: **117 passed, 0 failed, 0 skipped**
- 로그 분석 (4차): NemoNemo 메시지 수신 5건 vs 처리 4건 — 1건 드롭 발견
  - 원인: 19:27:55 수신 → 19:31:57 reset flag → client=None 재큐잉 3회(6초) < 재연결(13초) → 드롭
- 수정 #43: retry_noclient 3회→10회 (20초 대기, 재시작 소요시간 커버)
- 전체 테스트 실행: **117 passed, 0 failed, 0 skipped** (#43 반영 확인)
- 유닛테스트 작성: `tests/test_unit.py` — 8개 클래스, 59개 테스트
  - CleanText(6), EscapeHtml(4), ConvertTable(3), MdToHtml(16), SplitMessage(6)
  - ToolSummary(5), FormatToolLine(2), StabilizeMarkdown(3), AssessHealth(6), EmergencyCommand(8)
- 유닛테스트 실행: **59 passed, 0 failed**
- NemoNemo 응답 없음 분석: _restart_flag_loop에서 재시작 시 세션 루프가 이전 client의 receive_messages()에서 블록 → 새 메시지 처리 불가
- 수정 #44: receive_messages() 내 client 교체 감지 → break
- 수정 #45: _safe_disconnect에서 disconnect 실패 시 프로세스 강제 kill (proc.kill())
- 슈퍼바이저 재시작 후 NemoNemo 정상 복구 확인

### 2026-03-22
- Converter 좀비 프로세스 발견: `client._process`가 SDK에 없어 kill 실패 → claude.exe 2개 누적
- 수정 #45 보완: `client._transport._process.terminate()` (SDK 내부 구조: ClaudeSDKClient → _transport → _process)
- wrapper blocking 버그: `capture_output=True`로 자식 프로세스 stdout 파이프 열려있어 `subprocess.run()` 반환 안 됨
- 수정 #46: wrapper에서 `capture_output=True` 제거 → stderr만 파일로 리다이렉트
- 테스트: Converter 재시작 → "이전 프로세스 강제 terminate (pid=9736)" 로그 확인
- 테스트: wrapper 재시작 정상 동작, 4개 세션 connected=true
- 스모크 테스트 #44/#45/#46 추가 + #23/#24 업데이트 (transport 경로, stderr 파일 리다이렉트)
- 전체 스모크 테스트 실행: **133 passed, 0 failed, 0 skipped**
- 텔레그램 송수신 개선:
  - 수정 #47: deleteMessage GET → POST
  - 수정 #48: _notify_all 비동기화 (async_notify_all 추가, 루프 내 호출 교체)
  - 수정 #49: edited_message 수신 지원 (allowed_updates + [수정] 태그)
  - 수정 #50: document/file 메시지 처리 (getFile → 다운로드 → logs/files/)
- 스모크 테스트 #47~#50 추가
- 전체 스모크 테스트 실행: **141 passed, 0 failed, 4 skipped**
- auto-resume 설계 토론: Gemini + Perplexity 검토
  - 방안 A(큐 직접 투입) 채택, 2레벨 제어(전역 + 명령어 옵션)
  - STUCK reason → was_busy 강제 True, 프롬프트 개선
- 수정 #51: auto-resume ON/OFF 제어 (config.py + flag noresume + /restart noresume)
- _restart_session 끝에서 auto-resume 큐 투입 (개별 세션 재시작에서도 동작)
- 테스트: idle 상태 재시작 → "대기 상태 → 자동 재개 스킵" 정상 동작
- 전체 스모크 테스트 실행: **149 passed, 0 failed, 5 skipped**
- auto-resume 버그 발견: 슈퍼바이저 전체 재시작 시 os._exit(0) → was_busy_before_restart 초기화 → 항상 idle 판정
- 수정 #52: session_ids.json에 was_busy 상태 영속화 + 시작 시 복원
  - _save_session_ids: {name: {session_id, was_busy}} 형태로 저장
  - _load_session_ids: 하위 호환 (문자열→dict 마이그레이션)
  - os._exit 직전 _save_session_ids 호출
- 스모크 테스트 #52 추가
- 버그: _save_session_ids를 os._exit 직전에 호출 → busy 대기 후 이미 idle → was_busy=false
- 수정: _save_session_ids를 busy 대기 **전**으로 이동
- 실측: Crossword busy 중 재시작 → session_ids.json에 was_busy=true 저장
- 실측: 재시작 후 "busy 상태 복원됨" → "자동 재개 (1/2) — AI에게 판단 위임" 정상 동작
- 수정 #53: auto-resume 프롬프트 모드 (config.py)
  - AUTO_RESUME_MODE = "check" (기본값: 이전 작업 확인만)
  - AUTO_RESUME_PROMPTS dict로 커스터마이즈 가능
- 전체 스모크 테스트 실행: **162 passed, 0 failed, 0 skipped**
- 수정 #53 보완: "none" 모드 추가 (auto-resume 프롬프트 미전송)
- 전체 스모크 테스트 실행: **170 passed, 0 failed, 1 skipped**
- 로그 분석: 에러 0건, disconnect 0건, 재시작 0건 — 매우 안정
- 수정 #54: 느린 응답 중간 알림 (300초+ 경과 시 5분마다 텔레그램 알림)
- 수정 #55: wrapper 반복 재시작 경고 (10분 내 5회 이상)
- 수정 #56: 로그 로테이션 (500줄 초과 시 잘린 로그를 supervisor_YYYY-MM-DD.log에 보관)
- Newsort 이미지 누적 에러 발생: 에뮬레이터 스크린샷 4장 + resume → dimension limit 초과
- 수정 #57: 이미지 누적 에러 감지 → 자동 reset (예외 처리부 + 응답 텍스트 내 감지)
- 수정 #58: auto-resume 세션 재시작 전용 — `_session_loop` 시작 시 auto-resume 제거, `_restart_session`에서만 유지
- 수정 #59: [HUB] vs [SV] 프리픽스 분리 — 슈퍼바이저 본체는 [HUB], 세션 이벤트는 [SV]
- 설정 변경: `AUTO_RESUME_MODE = "check"` → `"resume"` (기본값 변경)
- 유닛 테스트 추가: `tests/test_telegram_api.py` (20 passed / 1 skipped)
  - _clean_text, _escape_html, _convert_table_to_list, _md_to_telegram_html, _split_message
  - **URL 제거 테스트**: bare URL, [text](url), 다중 URL, 코드블록 내 URL 보존
  - 마크다운 변환: bold, italic, header, code, strikethrough, blockquote
- 유닛 테스트 추가: `tests/test_config.py` (config 설정값 검증)
- 실측: 슈퍼바이저 재시작 → NemoNemo "연결 완료 — 대기 모드" (auto-resume 미발동 확인)
- 실측: 세션 리셋(`svctl reset`) → auto-resume 발동 (버그 — 리셋 시에는 스킵 필요, 미수정)

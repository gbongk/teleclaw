# 슈퍼바이저 연동 시나리오 테스트

## 자동 재개 (auto-resume)

### 1. resume 모드 재시작
- [입력] 세션 busy 상태에서 `/restart Converter`
- [기대] 재시작 후 "계속해줘" 자동 전송
- [확인] resume_count 1 증가

### 2. reset 모드 재시작
- [입력] `/reset Converter`
- [기대] 새 대화 시작, 자동 재개 안 함
- [확인] session_id = None

### 3. 대기 중 재시작 (busy=False)
- [입력] 세션 대기 상태에서 restart flag 생성
- [기대] 재시작 후 자동 재개 안 함 (was_busy=False)

### 4. session_id 유실 시
- [입력] session_ids.json 삭제 후 재시작
- [기대] 자동 재개 안 함 (맥락 유실)

### 5. resume_count 2회 초과
- [입력] 연속 2회 자동 재개 실패 (AI 응답 완료 전 재시작)
- [기대] 3번째는 스킵 + "⚠️ 자동 재개 2회 실패" 알림

### 6. 정상 완료 후 resume_count 리셋
- [입력] 자동 재개 → AI 정상 응답 완료
- [기대] resume_count = 0 리셋

### 7. 사용자 메시지 시 resume_count 리셋
- [입력] 자동 재개 후 사용자가 새 메시지
- [기대] resume_count = 0 리셋

## 중복 메시지

### 8. message_id 중복
- [입력] 같은 message_id의 update 2번 수신
- [기대] 2번째 스킵 (msg_key 기반)

### 9. 네트워크 재전송 중복
- [입력] 같은 date + 같은 텍스트의 다른 message_id
- [기대] 2번째 스킵 (date+text 기반, 로그에 "동일 date+텍스트 중복 스킵")

### 10. 의도적 동일 메시지
- [입력] 같은 텍스트를 10초 간격으로 2번 전송
- [기대] 둘 다 정상 처리 (date가 다르므로)

## Reply 및 수신 확인

### 11. 수신 확인 reply
- [입력] 사용자 메시지 전송
- [기대] `✔️ {텍스트}` 가 원본 메시지에 reply로 전송

### 12. AI 답변은 일반 메시지
- [입력] 사용자 메시지 → AI 응답
- [기대] AI 답변은 reply 아닌 일반 메시지로 전송

### 13. 완료 알림
- [입력] AI 응답 완료
- [기대] ✅ 메시지 전송

## 실시간 스트리밍

### 14. live edit 정상 동작
- [입력] AI가 긴 응답 생성
- [기대] 1초 간격으로 editMessage 업데이트

### 15. 메시지 분할 (live_lines > 1)
- [입력] AI가 매우 긴 응답 (2000자+ 또는 10초+)
- [기대] 기존 메시지 edit 마무리 + 새 메시지 시작
- [확인] live_lines가 1개일 때는 분할 안 함

### 16. 최종 HTML 변환
- [입력] AI 응답에 **볼드**, `코드` 포함
- [기대] 텔레그램에서 서식 적용되어 표시

### 17. HTML edit 실패 시
- [입력] HTML 파싱 에러 발생하는 마크다운
- [기대] plain text로 edit 재시도 (새 메시지 발송 안 함)

## 이미지 수신

### 18. 이미지 메시지
- [입력] 텔레그램에서 이미지 전송
- [기대] 이미지 다운로드 → "이 이미지를 확인해줘: {경로}" 로 AI에 전달

### 19. 이미지 + 캡션
- [입력] 텔레그램에서 이미지 + 캡션 "이게 뭐야?"
- [기대] "{캡션}\n\n이미지: {경로}" 로 AI에 전달

## 명령어

### 20. /help
- [입력] `/help`
- [기대] 명령어 목록 (/status, /usage, /log, /restart, /reset, /pause, /wakeup)

### 21. /log
- [입력] `/log 30`
- [기대] 최근 30줄 로그 반환

### 22. /status
- [입력] `/status`
- [기대] 세션별 상태 (connected, busy, query_count, error_count)

### 23. /pause + /wakeup
- [입력] `/pause Converter` → `/wakeup Converter`
- [기대] 일시정지 → 재개, 메시지 수신 중단/복구

---
## 테스트 기록

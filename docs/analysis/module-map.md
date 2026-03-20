# 슈퍼바이저 모듈 맵

## 패키지 `supervisor/supervisor/`

### config.py
| 이름 | 타입 | 설명 |
|---|---|---|
| `PROJECTS` | dict | 프로젝트별 설정 (cwd, bot_token, bot_id, mcp_json) |
| `CHAT_ID` | str | 텔레그램 채팅 ID |
| `SUPERVISOR_DIR` | str | 슈퍼바이저 루트 경로 |
| `LOGS_DIR` | str | 로그 디렉토리 |
| `DATA_DIR` | str | 런타임 데이터 디렉토리 |
| `TELEGRAM_DIR` | str | DATA_DIR 별칭 (flag 파일 호환) |
| `LOG_FILE` | str | supervisor.log 경로 |
| `LOCK_FILE` | str | supervisor.lock 경로 |
| `STATUS_FILE` | str | hub_status.json 경로 |
| `SESSION_IDS_FILE` | str | session_ids.json 경로 |
| `HEALTH_CHECK_INTERVAL` | int | 건강 체크 주기 (120s) |
| `STUCK_THRESHOLD` | int | STUCK 판정 (1800s) |
| `MAX_RESTARTS_PER_WINDOW` | int | 30분당 최대 재시작 (3) |
| `RESTART_WINDOW` | int | 재시작 윈도우 (1800s) |
| `SESSION_RESET_QUERIES` | int | 자동 리셋 쿼리 수 (100) |
| `SESSION_RESET_HOURS` | int | 자동 리셋 시간 (6h) |

### logging_utils.py
| 함수 | 설명 |
|---|---|
| `log(msg)` | 타임스탬프 로그 (콘솔 + 파일, 500줄 로테이션) |
| `_find_existing_supervisor()` → `int\|None` | WMI로 기존 supervisor.py 프로세스 PID 탐지 |
| `_write_lock()` | PID + 시작시간 lock 파일 생성 |
| `_release_lock()` | lock 파일 삭제 |

### telegram_api.py
| 함수 | 설명 |
|---|---|
| `send_telegram(text, bot_token, ...)` → `int` | 동기 전송, message_id 반환 |
| `edit_telegram(text, message_id, bot_token, ...)` → `bool` | 기존 메시지 수정 |
| `send_ack(bot_token, msg_id, ...)` | 확인 이모지 답장 |
| `async_send_telegram(ahttp, text, bot_token, ...)` → `int` | 비동기 전송 |
| `async_edit_telegram(ahttp, text, message_id, bot_token, ...)` → `bool` | 비동기 수정 |
| `async_react(ahttp, bot_token, msg_id, emoji)` | 메시지 리액션 추가 |
| `_notify_all(text)` | 전체 봇에 알림 브로드캐스트 |
| `_clean_text(text)` → `str` | 제어 문자 제거, cp949 복구, 빈줄 정리 |
| `_escape_html(text)` → `str` | HTML 특수문자 이스케이프 |
| `_convert_table_to_list(text)` → `str` | 마크다운 테이블 → 리스트 |
| `_md_to_telegram_html(text)` → `str` | GFM → 텔레그램 HTML |
| `_split_message(text, max_len)` → `list` | 의미 단위 메시지 분할 |

### session.py
| 클래스 | 설명 |
|---|---|
| `SessionState` | 프로젝트별 세션 상태 데이터클래스 |

| 필드 | 타입 | 설명 |
|---|---|---|
| `name` | str | 프로젝트명 |
| `config` | dict | PROJECTS 항목 |
| `client` | ClaudeSDKClient\|None | SDK 클라이언트 |
| `connected` | bool | 연결 상태 |
| `busy` | bool | 쿼리 처리 중 |
| `message_queue` | asyncio.Queue | 수신 메시지 큐 |
| `session_id` | str\|None | SDK 세션 ID (resume용) |
| `query_count` | int | 총 쿼리 수 |
| `restart_count` | int | 총 재시작 수 |
| `error_count` | int | 연속 에러 수 |
| `paused` | bool | 일시정지 |
| `restarting` | bool | 재시작 진행 중 |
| `resume_count` | int | 연속 자동 재개 (최대 2) |

### commands.py
| 함수 | 설명 |
|---|---|
| `handle_command(supervisor, text, bot_token)` → `bool` | 명령어 라우팅 (처리 시 True) |
| `_get_usage(http_client)` → `str` | OAuth 사용량 조회 (60초 캐시) |
| `_find_session_by_token(sessions, bot_token)` → `str\|None` | 봇 토큰으로 세션명 조회 |

| 명령어 | 핸들러 위치 |
|---|---|
| `/status` | handle_command 내부 |
| `/usage` | `_get_usage()` 호출 |
| `/sys` | handle_command 내부 (psutil) |
| `/log` | handle_command 내부 |
| `/restart` | Supervisor._restart_session 호출 |
| `/reset` | Supervisor._restart_session(mode="reset") 호출 |
| `/pause` | flag 파일 생성 |
| `/wakeup` | flag 파일 삭제 |
| `/ask` | Supervisor._handle_ask 호출 |
| `/help` | 텍스트 출력 |

### supervisor.py (패키지 내)
| 메서드 | 분류 | 설명 |
|---|---|---|
| `__init__()` | 초기화 | sessions, http client, watchdog 초기화 |
| `start()` | 초기화 | 세션 연결, 루프 병렬 시작 |
| `shutdown()` | 종료 | shutdown 플래그, lock 해제, 연결 종료 |
| `_connect_session(state, mode)` | 세션 | SDK 클라이언트 연결 (resume/reset) |
| `_restart_session(state, reason, mode)` | 세션 | 레이트 리밋 검사 후 재연결 |
| `_safe_disconnect(client, name)` | 세션 | 타임아웃 포함 안전 disconnect |
| `_flush_pending_updates(state)` | 세션 | pause→wakeup 시 메시지 flush |
| `_ensure_ask_client()` | 세션 | /ask 전용 클라이언트 lazy init |
| `_handle_ask(question, bot_token)` | 세션 | /ask 쿼리 처리 |
| `_session_loop(state)` | 루프 | 메시지 큐 → SDK query → 스트리밍 응답 전송 |
| `_bot_poll_loop(state)` | 루프 | 텔레그램 long polling → 큐 적재 |
| `_health_check_loop()` | 루프 | 2분 주기 DEAD/STUCK 감지 |
| `_restart_flag_loop()` | 루프 | 1초 주기 flag 파일 폴링 |
| `_watchdog_loop()` | 루프 | asyncio 데드락 감지 |
| `_start_watchdog_thread()` | 감시 | 워치독 스레드 시작 |
| `_assess_health(state)` | 감시 | 상태 판정 (OK/DEAD/STUCK/PAUSED) |
| `_save_session_ids()` | 영속 | session_ids.json 저장 |
| `_load_session_ids()` | 영속 | session_ids.json 복원 |
| `_write_status()` | 영속 | hub_status.json 갱신 |
| `_download_photo(msg, bot_token, name)` | 유틸 | 텔레그램 이미지 다운로드 |
| `_tool_summary(tool_name, input)` | 유틸 | 도구 호출 요약 |
| `_format_tool_line(tool_lines)` | 유틸 | 도구 체인 포맷 |
| `_stabilize_markdown(text)` | 유틸 | 열린 코드블록 닫기 |
| `_should_auto_resume(state)` | 유틸 | 자동 재개 판단 |
| `main()` | 진입점 | lock → 시그널 → start |

## 외부 파일

### supervisor-wrapper.py
| 함수 | 설명 |
|---|---|
| `log(msg)` | 래퍼 로그 (200줄 로테이션) |
| `tg_send(text)` | 텔레그램 알림 전송 |
| `tg_get_updates(offset, timeout)` | 비상 텔레그램 폴링 |
| `tg_flush(offset)` | 대기 메시지 소비 |
| `handle_emergency_command(text, ...)` | 비상 명령 (/log, /status, /restart, /kill, /ask) |
| `wait_with_polling(wait_sec, ...)` | 백오프 대기 + 비상 폴링 |
| `main()` | 슈퍼바이저 프로세스 spawn + 감시 루프 |

### relay-stop.py (Stop 훅)
| 함수 | 설명 |
|---|---|
| `get_config()` | .mcp.json에서 봇 설정 추출 |
| `is_supervised_session(session_id)` | 슈퍼바이저 관리 세션인지 확인 |
| `main()` | Claude 응답 완료 텍스트 → 텔레그램 중계 |

### relay-tool-use.py (PostToolUse 훅)
| 함수 | 설명 |
|---|---|
| `summarize(tool_name, tool_input)` | 도구 호출 요약 (Read/Edit/Bash/Grep 등) |
| `summarize_ai_chat_response(tool_name, response)` | ai-chat 응답 추출 |
| `get_last_assistant_text(transcript_path)` | JSONL 트랜스크립트에서 마지막 텍스트 |
| `main()` | 도구 사용 요약 + 텍스트 → 텔레그램 중계 |

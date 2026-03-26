# TeleClaw 모듈 맵

## 패키지 `hub/`

### config.py
| 이름 | 타입 | 설명 |
|---|---|---|
| `_load_yaml(path)` → `dict` | 함수 | config.yaml 파싱 (PyYAML 없이, 중첩 1단계) |
| `CHAT_ID` | str | 텔레그램 채팅 ID |
| `LANG` | str | 메시지 언어 ("ko"/"en") |
| `ALLOWED_USERS` | set | 허용된 사용자 ID 집합 (CHAT_ID 자동 포함) |
| `PROJECTS` | dict | 프로젝트별 설정 (cwd, bot_token, bot_id, mcp_json) |
| `SUPERVISOR_DIR` | str | 슈퍼바이저 루트 경로 |
| `LOGS_DIR` | str | 로그 디렉토리 |
| `LOG_FILE` | str | teleclaw.log 경로 |
| `LOCK_FILE` | str | teleclaw.lock 경로 |
| `STATUS_FILE` | str | hub_status.json 경로 |
| `SESSION_IDS_FILE` | str | session_ids.json 경로 |
| `DATA_DIR` | str | 런타임 데이터 디렉토리 |
| `TELEGRAM_DIR` | str | DATA_DIR 별칭 (flag 파일 호환) |
| `CLAUDE_SESSIONS_DIR` | str | ~/.claude/sessions 경로 |
| `HEALTH_CHECK_INTERVAL` | int | 건강 체크 주기 (120s) |
| `STUCK_THRESHOLD` | int | STUCK 판정 (1800s) |
| `MAX_RESTARTS_PER_WINDOW` | int | 30분당 최대 재시작 (3) |
| `RESTART_WINDOW` | int | 재시작 윈도우 (1800s) |
| `AUTO_RESUME_ENABLED` | bool | 자동 재개 활성화 |
| `AUTO_RESUME_MODE` | str | 재개 모드 ("resume"/"check"/"none") |
| `AUTO_RESUME_PROMPTS` | dict | 모드별 재개 프롬프트 |

### logging_utils.py
| 함수 | 설명 |
|---|---|
| `log(msg)` | 타임스탬프 로그 (콘솔 + 파일, 500줄 로테이션) |
| `_archive_lines(lines)` | 잘린 로그를 날짜별 teleclaw_YYYY-MM-DD.log에 보관. 7일 초과 자동 삭제 |
| `_find_existing_teleclaw()` → `int\|None` | lock 파일 + process_utils로 기존 teleclaw PID 탐지 |
| `_write_lock()` | PID + 시작시간 lock 파일 생성 |
| `_release_lock()` | lock 파일 삭제 |

### telegram_api.py
| 함수 | 설명 |
|---|---|
| `send_telegram(text, bot_token, ...)` → `int` | 동기 전송, message_id 반환. notify 파라미터 지원 |
| `edit_telegram(text, message_id, bot_token, ...)` → `bool` | 기존 메시지 수정 |
| `send_ack(bot_token, msg_id, ...)` | 확인 이모지 답장 |
| `_build_multipart(chat_id, field, file_path, caption)` → `(bytes, str)` | multipart/form-data body 구성 |
| `send_photo_sync(bot_token, file_path, caption)` → `int` | 동기 이미지 전송, message_id 반환 |
| `send_file_sync(bot_token, file_path, caption)` → `int` | 동기 파일 전송, message_id 반환 |
| `async_send_photo(ahttp, bot_token, file_path, caption)` → `int` | 비동기 이미지 전송 |
| `async_send_file(ahttp, bot_token, file_path, caption)` → `int` | 비동기 파일 전송 |
| `async_send_telegram(ahttp, text, bot_token, ...)` → `int` | 비동기 전송. reply_to 파라미터 지원 |
| `async_edit_telegram(ahttp, text, message_id, bot_token, ...)` → `bool` | 비동기 수정. HTML 폴백 |
| `async_react(ahttp, bot_token, msg_id, emoji)` | 메시지 리액션 추가 |
| `_notify_all(text)` | 전체 봇에 동기 브로드캐스트 |
| `async_notify_all(ahttp, text)` | 전체 봇에 비동기 브로드캐스트 |
| `_strip_urls(text)` → `str` | 마크다운 링크 → 텍스트만, bare URL 삭제 |
| `_clean_text(text)` → `str` | 제어 문자 제거, cp949 복구, URL 제거, 빈줄 정리 |
| `_escape_html(text)` → `str` | HTML 특수문자 이스케이프 |
| `_convert_table_to_list(text)` → `str` | 마크다운 테이블 → 리스트 |
| `_protect_code_blocks(text)` → `(str, list, list)` | 코드블록/인라인코드를 플레이스홀더로 치환 |
| `_restore_code_blocks(text, code_blocks, inline_codes)` → `str` | 플레이스홀더를 HTML 태그로 복원 |
| `_convert_markdown_formatting(text)` → `str` | 마크다운 서식 → HTML 태그 (***>**>*) |
| `_merge_blockquotes(text)` → `str` | 연속 인용줄을 하나의 blockquote로 병합 |
| `_md_to_telegram_html(text)` → `str` | GFM → 텔레그램 HTML 변환 파이프라인 |
| `_split_message(text, max_len)` → `list` | 의미 단위 메시지 분할 |

### channel.py
| 클래스 | 설명 |
|---|---|
| `Channel(ABC)` | 메시징 플랫폼 추상 인터페이스 |

| 메서드 | 분류 | 설명 |
|---|---|---|
| `name` (property) | 수신 | 채널 이름 ("telegram", "discord" 등) |
| `max_length` (property) | 수신 | 메시지 최대 길이 |
| `poll(timeout)` → `list` | 수신 | 새 메시지 폴링 (abstract) |
| `send(text, reply_to, use_markup)` → `str` | 전송 | 비동기 메시지 전송 (abstract) |
| `edit(message_id, text, use_markup)` → `bool` | 전송 | 메시지 편집 (abstract) |
| `delete(message_id)` → `bool` | 전송 | 메시지 삭제 (abstract) |
| `react(message_id, emoji)` → `bool` | 전송 | 리액션 추가 (abstract) |
| `send_sync(text, use_markup, notify)` → `str` | 전송 | 동기 메시지 전송 (abstract) |
| `send_photo(file_path, caption)` → `str` | 파일 | 비동기 이미지 전송 (abstract) |
| `send_file(file_path, caption)` → `str` | 파일 | 비동기 파일 전송 (abstract) |
| `send_photo_sync(file_path, caption)` → `str` | 파일 | 동기 이미지 전송 |
| `send_file_sync(file_path, caption)` → `str` | 파일 | 동기 파일 전송 |
| `download_file(file_ref)` → `bytes` | 파일 | 파일 다운로드 |
| `format(markdown_text)` → `str` | 포맷 | 마크다운 → 네이티브 포맷 변환 |
| `split(text)` → `list` | 포맷 | 메시지 분할 |
| `broadcast_sync(text)` | 브로드캐스트 | 전체 채널에 동기 알림 |
| `broadcast(text)` | 브로드캐스트 | 전체 채널에 비동기 알림 |

### channel_telegram.py
| 클래스 | 설명 |
|---|---|
| `TelegramChannel(Channel)` | 텔레그램 봇 기반 Channel 구현체 |

| 메서드 | 설명 |
|---|---|
| `__init__(bot_token, chat_id, bot_name, ahttp)` | 초기화 |
| `bot_token` / `chat_id` / `bot_name` (property) | 봇 설정 접근 |
| `set_ahttp(ahttp)` | AsyncClient 주입 |
| `poll(timeout)` → `list` | 텔레그램 long polling → 정규화된 메시지 목록 |
| `send(text, reply_to, use_markup)` → `str` | async_send_telegram 래핑 |
| `edit(message_id, text, use_markup)` → `bool` | async_edit_telegram 래핑 |
| `delete(message_id)` → `bool` | deleteMessage API 호출 |
| `react(message_id, emoji)` → `bool` | async_react 래핑 |
| `send_sync(text, use_markup, notify)` → `str` | send_telegram 래핑 |
| `send_photo(file_path, caption)` → `str` | async_send_photo 래핑 |
| `send_file(file_path, caption)` → `str` | async_send_file 래핑 |
| `send_photo_sync` / `send_file_sync` | 동기 파일 전송 래핑 |
| `download_file(file_ref)` → `bytes` | getFile → 다운로드 |
| `format(markdown_text)` → `str` | _md_to_telegram_html 래핑 |
| `split(text)` → `list` | _split_message 래핑 |
| `broadcast_sync(text)` / `broadcast(text)` | _notify_all / async_notify_all 래핑 |
| `get_offset()` / `set_offset(offset)` | 폴링 offset 관리 |

### messages.py
| 이름 | 타입 | 설명 |
|---|---|---|
| `_MESSAGES` | dict | 메시지 키 → {ko: str, en: str} 매핑 (약 80개) |
| `msg(key, **kwargs)` → `str` | 함수 | 현재 LANG에 맞는 메시지 반환. kwargs로 포맷팅 |

주요 메시지 카테고리: TeleClaw 상태, 세션 재시작, 세션 에러, 자동 재개, pause/wakeup, interrupt, /ask, /status, /usage, /ctx, /sys, /log, /help, 공통, wrapper, svctl

### session.py
| 클래스 | 설명 |
|---|---|
| `SessionState` | 프로젝트별 세션 상태 데이터클래스 |

| 필드 | 타입 | 설명 |
|---|---|---|
| `name` | str | 프로젝트명 |
| `config` | dict | PROJECTS 항목 |
| `client` | ClaudeSDKClient\|None | SDK 클라이언트 |
| `channel` | Channel\|None | 메시징 채널 |
| `connected` | bool | 연결 상태 |
| `busy` | bool | 쿼리 처리 중 |
| `message_queue` | asyncio.Queue | 수신 메시지 큐 |
| `error_count` | int | 연속 에러 수 |
| `start_time` | float | 세션 시작 시각 |
| `query_count` | int | 총 쿼리 수 |
| `restart_count` | int | 총 재시작 수 |
| `restart_history` | list | 재시작 시각 이력 |
| `last_notify_time` | float | 마지막 알림 시각 |
| `restarting` | bool | 재시작 진행 중 |
| `busy_since` | float | busy 시작 시각 |
| `session_id` | str\|None | SDK 세션 ID (resume용) |
| `resume_count` | int | 연속 자동 재개 (최대 2) |
| `last_restart_mode` | str | 마지막 재시작 모드 (resume/reset/crash) |
| `was_busy_before_restart` | bool | 재시작 전 busy 상태였는지 |
| `no_resume_before_restart` | bool | auto-resume 루프 방지 플래그 |

### commands.py
| 함수 | 설명 |
|---|---|
| `handle_command(teleclaw, text, bot_token, channel)` → `bool` | 명령어 라우팅 (처리 시 True). msg()로 i18n 응답 |
| `_do_interrupt(state, name, channel)` | 세션 현재 작업 중단 (interrupt) |
| `_get_usage(http_client)` → `str` | OAuth 사용량 조회 (60초 캐시). usage_fmt 사용 |
| `_find_session_by_token(sessions, bot_token)` → `str\|None` | 봇 토큰으로 세션명 조회 |

| 명령어 | 별칭 | 설명 |
|---|---|---|
| `/status` | `/s` | 세션 상태 + 가동 시간 |
| `/usage` | `/u` | 사용량 바 그래프 |
| `/ctx` | | 컨텍스트 사용량 (로그 기반 추정) |
| `/sys` | | CPU/메모리/디스크 + Claude 프로세스 목록 |
| `/log` | `/l` | 최근 로그 (기본 20줄, 최대 50줄) |
| `/restart` | `/r` | 세션 재시작 (noresume 옵션). `teleclaw` 지정 시 자체 재시작 |
| `/reset` | | 컨텍스트 초기화 재시작 |
| `/pause` | `/p` | 일시정지 + disconnect |
| `/esc` | `/interrupt` | 현재 작업 중단 |
| `/ask` | | Claude 질문 (별도 클라이언트) |
| `/help` | `/h` | 명령어 목록 |

### teleclaw.py (TeleClaw 클래스)
| 메서드 | 분류 | 설명 |
|---|---|---|
| `__init__()` | 초기화 | sessions, http client, 상태 변수 초기화 |
| `start()` | 초기화 | DB init, 세션/채널 생성, 병렬 연결, 루프 시작 |
| `shutdown()` | 종료 | shutdown 플래그, lock 해제, 연결 종료 |
| `_connect_session(state, mode)` | 세션 | SDK 클라이언트 연결 (resume/reset). DB 업데이트 |
| `_safe_disconnect(client, name)` | 세션 | 타임아웃 포함 안전 disconnect |
| `_wait_mcp_ready(state, timeout)` | 세션 | MCP 서버 초기화 대기 |
| `_ensure_ask_client()` → `bool` | 세션 | /ask 전용 클라이언트 lazy init |
| `_handle_ask(question, bot_token)` | 세션 | /ask 쿼리 처리 |
| `_restart_session(state, reason, mode, force, no_resume)` | 세션 | 레이트 리밋 검사 후 재연결. force/no_resume 옵션 |
| `_broadcast_sync(text)` | 전송 | 전체 채널에 동기 알림 |
| `_broadcast(text)` | 전송 | 전체 채널에 비동기 알림 |
| `_channel_by_token(bot_token)` | 전송 | 봇 토큰으로 채널 인스턴스 조회 |
| `_session_loop(state)` | 루프 | 메시지 큐 → SDK query → 스트리밍 응답 전송. 중복 메시지 제거, auto-resume, 이미지 처리 |
| `_bot_poll_loop(state)` | 루프 | 채널 poll → 명령어 라우팅/큐 적재, ALLOWED_USERS 필터링 |
| `_health_check_loop()` | 루프 | 2분 주기 DEAD/STUCK 감지 |
| `_restart_flag_loop()` | 루프 | 1초 주기 flag 파일 + DB 명령 폴링, busy 시 graceful 대기, TeleClaw 자체 재시작 지원 |
| `_watchdog_loop()` | 루프 | asyncio 데드락 감지 |
| `_start_watchdog_thread()` | 감시 | 워치독 스레드 시작 |
| `_assess_health(state)` → `str` | 감시 | 상태 판정 (OK/DEAD/STUCK/PAUSED) |
| `_save_offset(bot_id, offset)` | 영속 | 폴링 offset DB 저장 |
| `_load_offset(bot_id)` → `int\|None` | 영속 | 폴링 offset DB 로드 |
| `_save_session_ids(no_resume_if_busy)` | 영속 | session_ids.json 저장 |
| `_load_session_ids()` | 영속 | session_ids.json 복원 |
| `_write_status()` | 영속 | hub_status.json 갱신 |
| `_download_photo(msg, bot_token, name)` → `str` | 유틸 | 텔레그램 이미지 다운로드 (httpx) |
| `_download_photo_via_channel(ch, file_id, name)` → `str` | 유틸 | Channel 인터페이스로 이미지 다운로드 |
| `_download_doc_via_channel(ch, file_id, file_name, name)` → `str` | 유틸 | Channel 인터페이스로 문서 다운로드 |
| `_tool_summary(tool_name, input)` | 유틸 | 도구 호출 요약 (static) |
| `_format_tool_line(tool_lines)` | 유틸 | 도구 체인 포맷 (static) |
| `_stabilize_markdown(text)` | 유틸 | 열린 코드블록 닫기 (static) |
| `_should_auto_resume(state)` → `bool` | 유틸 | 자동 재개 판단 |
| `_handle_command(text, bot_token)` → `bool` | 유틸 | commands.handle_command 래핑 |
| `_find_session_by_token(bot_token)` → `str\|None` | 유틸 | 봇 토큰으로 세션명 조회 |
| `_get_usage()` → `str` | 유틸 | commands._get_usage 래핑 |
| `main()` | 진입점 | lock → 시그널 → start |

### state_db.py (SQLite 상태 관리)
| 함수 | 설명 |
|---|---|
| `init(db_path)` | DB 초기화 (teleClaw.db). 스키마 생성 |
| `_get_conn()` → `sqlite3.Connection` | 스레드별 커넥션 반환 (WAL 모드) |
| **세션 상태** | |
| `set_session(name, **kwargs)` | 세션 상태 upsert |
| `get_session(name)` → `dict` | 세션 상태 조회 |
| `get_all_sessions()` → `dict` | 전체 세션 상태 |
| `delete_session(name)` | 세션 삭제 |
| **명령 큐** | |
| `push_command(target, command, args)` | 명령 추가 |
| `pop_command(target)` → `dict` | 미처리 명령 1개 FIFO |
| `pop_commands(target)` → `list` | 미처리 명령 전부 |
| `has_pending_command(target, command)` → `bool` | 미처리 명령 존재 확인 |
| **relay 설정** | |
| `set_relay(bot_id, chat_id, enabled)` | relay 활성화/비활성화 |
| `is_relay_enabled(bot_id, chat_id)` → `bool` | relay 활성화 여부 |
| **폴링 offset** | |
| `set_offset(bot_id, offset)` | 폴링 offset 저장 |
| `get_offset(bot_id)` → `int` | 폴링 offset 조회 |
| **전역 상태** | |
| `set_state(key, value)` | KV 저장 |
| `get_state(key, default)` → `str` | KV 조회 |
| **하위 호환** | |
| `is_paused(name)` → `bool` | 일시정지 상태 확인 |
| `set_paused(name, paused)` | 일시정지 설정/해제 |
| **정리** | |
| `cleanup_old_commands(max_age_hours)` | 오래된 처리 완료 명령 삭제 |

DB 테이블: `sessions`, `commands`, `relay_config`, `poll_offsets`, `supervisor_state`

### usage_fmt.py
| 함수 | 설명 |
|---|---|
| `usage_bar(pct, emoji)` → `str` | 20칸 바 포맷. 색상 아이콘 포함 가능 |
| `reset_str(bucket)` → `str` | 리셋 시간까지 남은 시간 문자열 |

### process_utils.py
| 함수 | 설명 |
|---|---|
| `is_pid_alive(pid)` → `bool` | PID 실행 확인 (psutil → tasklist/kill 폴백) |
| `kill_pid(pid)` | PID 강제 종료 (크로스 플랫폼) |
| `find_processes(name_pattern)` → `list` | 이름 패턴으로 프로세스 검색 |

### service.py (시스템 서비스)
| 함수 | 설명 |
|---|---|
| `install()` | 시스템 서비스 등록 (systemd/Task Scheduler) |
| `uninstall()` | 서비스 해제 |
| `status()` | 서비스 상태 확인 |
| `logs(n)` | 서비스 로그 조회 |

내부: `_systemd_install/uninstall/status/logs`, `_schtasks_install/uninstall/status/logs`

### `__init__.py`
| 이름 | 설명 |
|---|---|
| `main()` | CLI 진입점 — 서브커맨드 지원 (install/uninstall/status/logs 또는 TeleClaw 실행) |
| `__all__` | TeleClaw, SessionState, main, log, Channel, TelegramChannel, PROJECTS |

### `__main__.py`
`python -m hub` 지원. `main()` 호출.

---

## 외부 파일 (루트)

### teleclaw-wrapper.py
| 함수 | 설명 |
|---|---|
| `log(msg)` | 래퍼 로그 (200줄 로테이션) |
| `tg_send(text)` | 텔레그램 알림 전송 (urllib) |
| `tg_get_updates(offset, timeout, bot_token)` → `(list, int)` | 텔레그램 폴링. ALLOWED_USERS 필터링 |
| `tg_flush(offset, bot_token)` → `int` | 대기 메시지 소비 |
| `handle_emergency_command(text, ...)` → `str\|None` | 비상 명령 (/log, /status, /restart, /kill, /ask). msg() 사용 |
| `wait_with_polling(wait_sec, ...)` → `str\|None` | 백오프 대기 + 비상 폴링 (3개 봇 순차) |
| `_acquire_lock()` / `_release_lock()` | 래퍼 단일 인스턴스 보장 |
| `main()` | TeleClaw 프로세스 spawn + 감시 루프 (지수 백오프, 잦은 재시작 경고) |

### relay_common.py
| 함수 | 설명 |
|---|---|
| `get_config()` → `tuple\|None` | .mcp.json에서 봇 설정 추출 (bot_token, chat_id, bot_name) |
| `is_relay_enabled(bot_id, chat_id)` → `bool` | DB + flag 파일 듀얼 체크 |
| `is_supervised_session(session_id)` → `bool` | TeleClaw 관리 세션인지 확인 |
| `_send_telegram_multipart(bot_token, chat_id, field, file_path, caption)` | multipart 전송 (urllib, 훅용 경량) |
| `send_telegram_photo(bot_token, chat_id, photo_path, caption)` | 이미지 전송 |
| `send_telegram_file(bot_token, chat_id, file_path, caption)` | 파일 전송 |
| `send_telegram(bot_token, chat_id, text)` | 텍스트 전송 (urllib) |

### send_telegram.py (CLI 래퍼)
| 함수 | 설명 |
|---|---|
| `_match_project()` → `(bot_token, name)` | cwd 기반 PROJECTS 매칭 |
| `__main__` | `hub.telegram_api.send_photo_sync` / `send_file_sync` 호출 |

Usage: `python send_telegram.py <photo|file> <path> [caption]`

### relay-stop.py (Stop 훅)
| 함수 | 설명 |
|---|---|
| `log(msg)` | 디버그 로그 (300줄 로테이션) |
| `should_skip(hook_data)` → `bool` | wait_for_message 등 스킵 패턴 |
| `main()` | Claude 응답 완료 텍스트 → 텔레그램 중계. relay_common 사용 |

### relay-tool-use.py (PostToolUse 훅)
| 함수 | 설명 |
|---|---|
| `summarize(tool_name, tool_input)` → `str` | 도구 호출 요약 (Read/Edit/Bash/Grep/MCP 등) |
| `summarize_ai_chat_response(tool_name, response)` → `str\|None` | ai-chat 응답 추출 |
| `get_last_assistant_text(transcript_path)` → `str\|None` | JSONL 트랜스크립트에서 마지막 텍스트 |
| `filter_assistant_text(text)` → `str` | 노이즈 제거 (Shell cwd, OK/PASS 압축, 도구 라인 제거) |
| `load_last_sent(session_id)` / `save_last_sent(session_id, text)` | 중복 전송 방지용 캐시 |
| `main()` | 도구 사용 요약 + 텍스트 → 텔레그램 중계. 스크린샷은 사진 전송 |

### relay-screenshot.py (PostToolUse 훅)
| 함수 | 설명 |
|---|---|
| `main()` | emulator screenshot 도구 응답에서 경로 추출 → relay_common.send_telegram_photo로 전송 |

### svctl.py (CLI 도구)
| 함수 | 설명 |
|---|---|
| `_guess_session()` → `str\|None` | cwd 기반 세션 추정 |
| `_resolve_name(arg)` → `str\|None` | 인자에서 세션명 해석 (대소문자 무시) |
| `_get_all_processes()` → `dict` | claude + teleclaw 프로세스 조회 (psutil/PowerShell) |
| `cmd_sys()` | 시스템 CPU/메모리 |
| `cmd_ps()` | 프로세스 목록 + 세션 매핑 + 메모리 합계 |
| `cmd_restart(arg, mode)` | flag 파일로 재시작 요청 |
| `cmd_pause(arg)` | flag + 프로세스 kill |
| `cmd_log(arg)` | 최근 로그 출력 |
| `cmd_usage()` | OAuth 사용량 바 그래프 (usage_fmt 사용) |
| `cmd_ctx()` | 컨텍스트 사용량 (transcript jsonl 분석) |
| `cmd_help()` | 명령어 목록 |
| `main()` | 명령어 라우팅 |

| 명령어 | 별칭 | 설명 |
|---|---|---|
| `ps` | `s`, `status` | 프로세스 상태 |
| `sys` | `system` | CPU/메모리 |
| `restart` | `r` | 세션/TeleClaw 재시작 |
| `reset` | | 컨텍스트 초기화 |
| `pause` | `p` | 일시정지 |
| `ctx` | `c` | 컨텍스트 사용량 |
| `log` | `l` | 로그 조회 |
| `usage` | `u` | 사용량 |
| `help` | `h` | 도움말 |

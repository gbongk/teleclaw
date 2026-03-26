"""i18n 메시지 — 사용자 노출 텍스트의 한국어/영어 지원.

사용법:
    from .messages import msg
    msg("restart_done", name="Converter")  # → "[SV] Converter: 재시작 완료, ..."
"""

from .config import LANG

_MESSAGES = {
    # --- TeleClaw 상태 ---
    "sv_start": {
        "ko": "[HUB] TeleClaw 시작",
        "en": "[HUB] TeleClaw starting",
    },
    "sv_ready": {
        "ko": "[SV] 시작 완료 — 메시지 수신 준비됨",
        "en": "[SV] Ready — waiting for messages",
    },
    "sv_init_done": {
        "ko": "[HUB] 초기화 완료 ({elapsed}초) — {names} 연결됨",
        "en": "[HUB] Init done ({elapsed}s) — {names} connected",
    },
    "sv_task_error": {
        "ko": "[HUB] task[{i}] 에러: {error}",
        "en": "[HUB] task[{i}] error: {error}",
    },
    "sv_connected": {
        "ko": "[SV] {name}: 연결 완료",
        "en": "[SV] {name}: connected",
    },
    "sv_shutting_down": {
        "ko": "[HUB] TeleClaw 종료 중...",
        "en": "[HUB] TeleClaw shutting down...",
    },
    "sv_self_restart": {
        "ko": "[HUB] 자체 재시작 요청 (mode={mode})",
        "en": "[HUB] Self-restart requested (mode={mode})",
    },

    # --- 세션 재시작 ---
    "restart_reason": {
        "ko": "[SV] {name}: {reason} → 재시작",
        "en": "[SV] {name}: {reason} → restarting",
    },
    "restart_done": {
        "ko": "[SV] {name}: 재시작 완료, 메시지 수신 준비됨",
        "en": "[SV] {name}: restart complete, ready for messages",
    },
    "restart_limit": {
        "ko": "[WARN] {name}: 재시작 한도 초과 ({max}회/{window}분)\n사유: {reason}\n{remaining}초 후 자동 재시도",
        "en": "[WARN] {name}: restart limit reached ({max}/{window}min)\nReason: {reason}\nAuto-retry in {remaining}s",
    },
    "restart_requested": {
        "ko": "[SV] {name} 재시작 요청됨{tag}",
        "en": "[SV] {name} restart requested{tag}",
    },
    "reset_requested": {
        "ko": "[SV] {name} 리셋 요청됨",
        "en": "[SV] {name} reset requested",
    },
    "sv_restart_requested": {
        "ko": "[SV] TeleClaw 재시작합니다...",
        "en": "[SV] TeleClaw restarting...",
    },

    # --- 세션 에러 ---
    "session_not_found": {
        "ko": "[SV] 세션 '{name}' 없음. 가능: {available}",
        "en": "[SV] Session '{name}' not found. Available: {available}",
    },
    "session_not_connected": {
        "ko": "[SV] {name}: 연결 안 됨",
        "en": "[SV] {name}: not connected",
    },
    "session_init_fail": {
        "ko": "❌ 세션 초기화 실패, 메시지 처리 불가\n원본: {text}",
        "en": "❌ Session init failed, cannot process message\nOriginal: {text}",
    },
    "session_connect_fail": {
        "ko": "❌ 세션 연결 실패, 메시지 처리 불가\n원본: {text}",
        "en": "❌ Session connection failed, cannot process\nOriginal: {text}",
    },
    "process_fail": {
        "ko": "❌ 처리 실패: {error}\n원본: {text}",
        "en": "❌ Processing failed: {error}\nOriginal: {text}",
    },
    "empty_response": {
        "ko": "⚠️ 빈 응답",
        "en": "⚠️ Empty response",
    },
    "timeout_exhausted": {
        "ko": "❌ 응답 타임아웃 (재시도 소진)\n원본: {text}",
        "en": "❌ Response timeout (retries exhausted)\nOriginal: {text}",
    },

    # --- 자동 재개 ---
    "auto_resume_fail": {
        "ko": "⚠️ {name}: 자동 재개 2회 실패, 중단했습니다. 수동 확인 필요.",
        "en": "⚠️ {name}: auto-resume failed twice, stopped. Manual check needed.",
    },

    # --- 이미지/컨텍스트 ---
    "image_overflow": {
        "ko": "⚠️ 이미지 누적으로 컨텍스트 초과\n자동 reset 진행",
        "en": "⚠️ Context overflow due to image accumulation\nAuto-reset in progress",
    },

    # --- 진행 상태 ---
    "still_processing": {
        "ko": "⏳ 아직 처리 중... ({mins}분 경과, 도구 {tools}회 호출)",
        "en": "⏳ Still processing... ({mins}min elapsed, {tools} tool calls)",
    },
    "pending_message": {
        "ko": "── 대기 메시지 처리 ──\n💬 {text}",
        "en": "── Processing queued message ──\n💬 {text}",
    },

    # --- pause/wakeup ---
    "paused": {
        "ko": "[SV] {name} 일시정지됨",
        "en": "[SV] {name} paused",
    },
    "already_paused": {
        "ko": "[SV] {name} 이미 일시정지 상태입니다",
        "en": "[SV] {name} already paused",
    },
    "pause_unpause_restart": {
        "ko": "▶️ {name} pause 해제 + 재시작 요청됨",
        "en": "▶️ {name} unpaused + restart requested",
    },
    "paused_hint": {
        "ko": "⏸️ {name} 일시정지 중. restart 또는 reset을 입력하세요.",
        "en": "⏸️ {name} is paused. Send restart or reset.",
    },

    # --- interrupt ---
    "interrupted": {
        "ko": "[SV] {name}: 작업 중단됨",
        "en": "[SV] {name}: interrupted",
    },
    "interrupt_fail": {
        "ko": "[SV] {name}: interrupt 실패 ({error})",
        "en": "[SV] {name}: interrupt failed ({error})",
    },

    # --- /ask ---
    "ask_busy": {
        "ko": "[SV] /ask 처리 중입니다. 잠시 후 다시 시도하세요.",
        "en": "[SV] /ask is busy. Please try again later.",
    },
    "ask_connect_fail": {
        "ko": "[SV] ask 세션 연결 실패",
        "en": "[SV] ask session connection failed",
    },
    "ask_processing": {
        "ko": "[SV] 질문 중...",
        "en": "[SV] Processing question...",
    },
    "ask_response": {
        "ko": "[SV] Claude:\n{answer}",
        "en": "[SV] Claude:\n{answer}",
    },
    "ask_error": {
        "ko": "[SV] ask 오류: {error}",
        "en": "[SV] ask error: {error}",
    },
    "ask_usage": {
        "ko": "[SV] 사용법: /ask <질문>",
        "en": "[SV] Usage: /ask <question>",
    },

    # --- /status ---
    "status_header": {
        "ko": "[SV] 가동 {h}시간 {m}분",
        "en": "[SV] Uptime {h}h {m}m",
    },

    # --- /usage ---
    "usage_header": {
        "ko": "[SV] Claude 사용량",
        "en": "[SV] Claude Usage",
    },
    "usage_fail_cred": {
        "ko": "[SV] 사용량 조회 실패: credentials 읽기 에러 ({error})",
        "en": "[SV] Usage query failed: credentials error ({error})",
    },
    "usage_fail_http": {
        "ko": "[SV] 사용량 조회 실패: HTTP {code}",
        "en": "[SV] Usage query failed: HTTP {code}",
    },
    "usage_fail": {
        "ko": "[SV] 사용량 조회 실패: {error}",
        "en": "[SV] Usage query failed: {error}",
    },

    # --- /ctx ---
    "ctx_header": {
        "ko": "[SV] 컨텍스트 사용량 (추정)",
        "en": "[SV] Context usage (estimated)",
    },
    "ctx_no_data": {
        "ko": "  {name}: 데이터 없음",
        "en": "  {name}: no data",
    },
    "ctx_note": {
        "ko": "\n⚠️ SDK usage 기반 추정값. 정확한 ctx%는 CLI 상태줄 참조",
        "en": "\n⚠️ Estimated from SDK usage. Check CLI status line for exact ctx%",
    },

    # --- /sys ---
    "sys_header": {
        "ko": "[SV] 시스템 상태",
        "en": "[SV] System Status",
    },
    "sys_cpu": {
        "ko": "\U0001f5a5 CPU: {pct}% ({cores}코어)",
        "en": "\U0001f5a5 CPU: {pct}% ({cores} cores)",
    },
    "sys_mem": {
        "ko": "\U0001f4be 메모리: {used:.1f}/{total:.1f}GB ({pct}%)",
        "en": "\U0001f4be Memory: {used:.1f}/{total:.1f}GB ({pct}%)",
    },
    "sys_disk": {
        "ko": "\U0001f4c1 디스크: {used:.0f}/{total:.0f}GB ({pct}%)",
        "en": "\U0001f4c1 Disk: {used:.0f}/{total:.0f}GB ({pct}%)",
    },
    "sys_procs_header": {
        "ko": "\n\U0001f4cb 프로세스 (상위 {limit}개):",
        "en": "\n\U0001f4cb Processes (top {limit}):",
    },
    "sys_no_procs": {
        "ko": "  Claude 관련 프로세스 없음",
        "en": "  No Claude-related processes",
    },
    "sys_supervisor": {
        "ko": "\n\U0001f916 TeleClaw: PID:{pid} {mem:.0f}MB",
        "en": "\n\U0001f916 TeleClaw: PID:{pid} {mem:.0f}MB",
    },
    "sys_no_psutil": {
        "ko": "psutil 미설치. pip install psutil",
        "en": "psutil not installed. pip install psutil",
    },

    # --- /log ---
    "log_header": {
        "ko": "[SV] 최근 로그 ({n}줄)\n",
        "en": "[SV] Recent logs ({n} lines)\n",
    },
    "log_read_fail": {
        "ko": "[SV] 로그 읽기 실패: {error}",
        "en": "[SV] Log read failed: {error}",
    },

    # --- /help ---
    "help_text": {
        "ko": (
            "[SV] 명령어\n\n"
            "\U0001f4ca 상태\n"
            "  /status (/s) \u2014 세션 상태\n"
            "  /usage  (/u) \u2014 사용량\n"
            "  /ctx \u2014 컨텍스트 사용량\n"
            "  /sys \u2014 시스템\n"
            "  /log (/l) [N] \u2014 로그\n\n"
            "\U0001f504 세션\n"
            "  /esc <name> \u2014 작업 중단 (interrupt)\n"
            "  /pause (/p) <name> \u2014 일시정지\n"
            "  /restart (/r) <name> [noresume] \u2014 재시작\n"
            "  /reset <name> \u2014 리셋\n\n"
            "\u2139\ufe0f 기타\n"
            "  /ask <질문> \u2014 Claude 질문\n"
            "  /help (/h) \u2014 이 목록\n\n"
            "세션: {names}"
        ),
        "en": (
            "[SV] Commands\n\n"
            "\U0001f4ca Status\n"
            "  /status (/s) \u2014 session status\n"
            "  /usage  (/u) \u2014 usage\n"
            "  /ctx \u2014 context usage\n"
            "  /sys \u2014 system\n"
            "  /log (/l) [N] \u2014 logs\n\n"
            "\U0001f504 Session\n"
            "  /esc <name> \u2014 interrupt\n"
            "  /pause (/p) <name> \u2014 pause\n"
            "  /restart (/r) <name> [noresume] \u2014 restart\n"
            "  /reset <name> \u2014 reset\n\n"
            "\u2139\ufe0f Other\n"
            "  /ask <question> \u2014 ask Claude\n"
            "  /help (/h) \u2014 this list\n\n"
            "Sessions: {names}"
        ),
    },

    # --- 공통 ---
    "shutdown_not_allowed": {
        "ko": "[SV] TeleClaw 종료는 채팅방에서 불가합니다.",
        "en": "[SV] Cannot shutdown TeleClaw from chat.",
    },
    "error_generic": {
        "ko": "오류: {error}",
        "en": "Error: {error}",
    },
    "unauthorized": {
        "ko": "[SV] 권한 없는 사용자입니다.",
        "en": "[SV] Unauthorized user.",
    },

    # --- wrapper ---
    "wrapper_emergency_status": {
        "ko": "🔧 래퍼 비상 모드\n가동: {h}시간 {m}분\n연속 실패: {fails}회\n백오프: {wait}초\nTeleClaw: 중지됨",
        "en": "🔧 Wrapper emergency mode\nUptime: {h}h {m}m\nConsecutive failures: {fails}\nBackoff: {wait}s\nTeleClaw: stopped",
    },
    "wrapper_restarting": {
        "ko": "🔄 TeleClaw 즉시 재시작합니다.",
        "en": "🔄 Restarting TeleClaw immediately.",
    },
    "wrapper_killed": {
        "ko": "🛑 래퍼를 종료합니다. 수동 시작이 필요합니다.",
        "en": "🛑 Wrapper stopped. Manual start required.",
    },
    "wrapper_help": {
        "ko": (
            "🔧 래퍼 비상 명령어:\n"
            "  /status — 상태\n"
            "  /restart — 즉시 재시작\n"
            "  /kill — 래퍼 종료\n"
            "  /ask <메시지> — Claude에게 질문\n"
            "  /help — 이 목록"
        ),
        "en": (
            "🔧 Wrapper emergency commands:\n"
            "  /status — status\n"
            "  /restart — restart now\n"
            "  /kill — stop wrapper\n"
            "  /ask <message> — ask Claude\n"
            "  /help — this list"
        ),
    },
    "wrapper_ask_usage": {
        "ko": "사용법: /ask <질문>",
        "en": "Usage: /ask <question>",
    },
    "wrapper_ask_processing": {
        "ko": "🤖 Claude에게 질문 중...",
        "en": "🤖 Asking Claude...",
    },
    "wrapper_ask_response": {
        "ko": "🤖 Claude:\n{answer}",
        "en": "🤖 Claude:\n{answer}",
    },
    "wrapper_ask_error": {
        "ko": "❌ Claude 에러:\n{error}",
        "en": "❌ Claude error:\n{error}",
    },
    "wrapper_ask_empty": {
        "ko": "🤖 Claude: (빈 응답)",
        "en": "🤖 Claude: (empty response)",
    },
    "wrapper_ask_timeout": {
        "ko": "⏰ Claude 응답 시간 초과 (2분)",
        "en": "⏰ Claude response timeout (2min)",
    },
    "wrapper_ask_fail": {
        "ko": "❌ Claude 실행 실패: {error}",
        "en": "❌ Claude execution failed: {error}",
    },
    "wrapper_crash": {
        "ko": "⚠️ TeleClaw 비정상 종료\n생존시간: {elapsed:.0f}초\nexit_code: {code}\n연속 실패: {fails}회\n다음 재시도: {wait}초 후\n비상 명령: /help",
        "en": "⚠️ TeleClaw abnormal exit\nAlive: {elapsed:.0f}s\nexit_code: {code}\nConsecutive failures: {fails}\nNext retry: {wait}s\nEmergency: /help",
    },
    "wrapper_crash_stderr": {
        "ko": "🔍 teleclaw 크래시 stderr:\n{stderr}",
        "en": "🔍 TeleClaw crash stderr:\n{stderr}",
    },
    "wrapper_frequent_restart": {
        "ko": "⚠️ 잦은 재시작 감지: {count}회/10분\n마지막 생존: {elapsed:.0f}초, exit_code={code}",
        "en": "⚠️ Frequent restarts detected: {count}/10min\nLast alive: {elapsed:.0f}s, exit_code={code}",
    },
    "wrapper_already_running": {
        "ko": "이미 래퍼가 실행 중입니다.",
        "en": "Wrapper is already running.",
    },

    # --- svctl ---
    "svctl_specify_session": {
        "ko": "세션 이름을 지정하세요: {names}",
        "en": "Specify a session name: {names}",
    },
    "svctl_session_not_found": {
        "ko": "세션 '{name}' 없음. 가능: {available}",
        "en": "Session '{name}' not found. Available: {available}",
    },
    "svctl_need_psutil": {
        "ko": "psutil이 필요합니다: pip install psutil",
        "en": "psutil required: pip install psutil",
    },
    "svctl_sv_running": {
        "ko": "TeleClaw PID={pid} 가동: {h}시간 {m}분",
        "en": "TeleClaw PID={pid} uptime: {h}h {m}m",
    },
    "svctl_sv_not_running": {
        "ko": "TeleClaw 미실행",
        "en": "TeleClaw not running",
    },
    "svctl_total": {
        "ko": "  합계: {mem}MB",
        "en": "  Total: {mem}MB",
    },
    "svctl_restart_sv": {
        "ko": "TeleClaw 재시작 요청됨",
        "en": "TeleClaw restart requested",
    },
    "svctl_restart_session": {
        "ko": "{name} 재시작 요청됨{mode}",
        "en": "{name} restart requested{mode}",
    },
    "svctl_specify_session_no_sv": {
        "ko": "세션 이름을 지정하세요 (teleclaw 불가)",
        "en": "Specify a session name (not teleclaw)",
    },
    "svctl_paused": {
        "ko": "{name} 일시정지됨 (PID={pid} 종료)",
        "en": "{name} paused (PID={pid} killed)",
    },
    "svctl_pause_flag_only": {
        "ko": "{name} 일시정지 플래그 생성됨 (프로세스 종료 실패)",
        "en": "{name} pause flag created (process kill failed)",
    },
    "svctl_paused_no_proc": {
        "ko": "{name} 일시정지됨 (프로세스 없음)",
        "en": "{name} paused (no process)",
    },
    "svctl_no_log": {
        "ko": "로그 파일 없음",
        "en": "No log file",
    },
    "svctl_cred_fail": {
        "ko": "credentials 읽기 실패: {error}",
        "en": "Failed to read credentials: {error}",
    },
    "svctl_usage_fail_http": {
        "ko": "사용량 조회 실패: HTTP {code}",
        "en": "Usage query failed: HTTP {code}",
    },
    "svctl_usage_fail": {
        "ko": "사용량 조회 실패: {error}",
        "en": "Usage query failed: {error}",
    },
    "svctl_no_session_ids": {
        "ko": "session_ids.json 없음",
        "en": "session_ids.json not found",
    },
    "svctl_no_session": {
        "ko": "  {name}: 세션 없음",
        "en": "  {name}: no session",
    },
    "svctl_no_mapping": {
        "ko": "  {name}: 매핑 없음",
        "en": "  {name}: no mapping",
    },
    "svctl_no_transcript": {
        "ko": "  {name}: transcript 없음",
        "en": "  {name}: no transcript",
    },
    "svctl_no_usage": {
        "ko": "  {name}: usage 데이터 없음",
        "en": "  {name}: no usage data",
    },
    "svctl_error": {
        "ko": "  {name}: 오류 - {error}",
        "en": "  {name}: error - {error}",
    },
    "svctl_unknown_cmd": {
        "ko": "알 수 없는 명령: {cmd}",
        "en": "Unknown command: {cmd}",
    },
    "svctl_help": {
        "ko": (
            "사용법: svctl <명령> [인자]\n\n"
            "  ps          프로세스 상태\n"
            "  restart     세션/TeleClaw 재시작\n"
            "  pause       세션 일시정지\n"
            "  log [N]     최근 로그 (기본 20줄)\n"
            "  usage       사용량 조회\n"
            "  ctx         컨텍스트 사용량\n"
            "  help        이 목록"
        ),
        "en": (
            "Usage: svctl <command> [args]\n\n"
            "  ps          process status\n"
            "  restart     restart session/teleclaw\n"
            "  pause       pause session\n"
            "  log [N]     recent logs (default 20)\n"
            "  usage       usage info\n"
            "  ctx         context usage\n"
            "  help        this list"
        ),
    },
    "svctl_sys_fail": {
        "ko": "시스템 정보 조회 실패",
        "en": "Failed to query system info",
    },
}


def msg(key: str, **kwargs) -> str:
    """메시지 키로 현재 언어의 텍스트를 반환한다. kwargs로 포맷팅."""
    entry = _MESSAGES.get(key)
    if not entry:
        return key
    text = entry.get(LANG, entry.get("en", key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text

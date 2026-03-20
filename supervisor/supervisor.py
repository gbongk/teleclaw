"""
텔레그램 슈퍼바이저 — Claude Code SDK 기반 텔레그램 봇
텔레그램 메시지 수신 → SDK query → 응답 → 텔레그램 전송.
health check, 재시작, 상태 관리, watchdog 통합.
"""

import os
import sys
import json
import time
import asyncio
import signal
import threading
import httpx
from pathlib import Path

# Windows cp949 인코딩 문제 방지 — stdout/stderr를 UTF-8로 강제
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from claude_code_sdk import (
    ClaudeSDKClient, ClaudeCodeOptions,
    SystemMessage, AssistantMessage, UserMessage, ResultMessage,
)

# monkey-patch: rate_limit_event 캡처 + 알 수 없는 타입 무시
import claude_code_sdk._internal.message_parser as _mp
_original_parse = _mp.parse_message
_rate_limit_data = {}  # session_id → {status, utilization, resetsAt, ts}
def _patched_parse(data):
    try:
        return _original_parse(data)
    except Exception:
        if isinstance(data, dict) and data.get("type") == "rate_limit_event":
            info = data.get("rate_limit_info", {})
            sid = data.get("session_id", "")
            _rate_limit_data[sid] = {
                "status": info.get("status"),
                "utilization": info.get("utilization"),
                "resetsAt": info.get("resetsAt"),
                "ts": time.time(),
            }
        return None
_mp.parse_message = _patched_parse

from .config import (
    PROJECTS, CHAT_ID, SUPERVISOR_DIR, LOGS_DIR, LOG_FILE,
    STATUS_FILE, SESSION_IDS_FILE, TELEGRAM_DIR,
    HEALTH_CHECK_INTERVAL, STUCK_THRESHOLD,
    MAX_RESTARTS_PER_WINDOW, RESTART_WINDOW,
    SESSION_RESET_QUERIES, SESSION_RESET_HOURS,
)
from .logging_utils import log, _find_existing_supervisor, _write_lock, _release_lock
from .telegram_api import (
    send_telegram, edit_telegram, send_ack,
    _clean_text, _escape_html, _convert_table_to_list,
    _md_to_telegram_html, _split_message,
    async_send_telegram, async_edit_telegram, async_react,
    _notify_all,
)
from .session import SessionState
from .commands import handle_command, _get_usage


class Supervisor:
    def __init__(self):
        self.sessions: dict[str, SessionState] = {}
        self._shutdown = False
        self._http = httpx.Client(timeout=35)
        self._ahttp: httpx.AsyncClient | None = None
        self._update_ids: dict[str, int] = {}
        self._watchdog_ts = time.time()
        self._start_time = time.time()
        self._last_msg_map: dict[str, float] = {}  # 중복 메시지 제거용
        self._ask_client: ClaudeSDKClient | None = None
        self._ask_busy = False

    async def start(self):
        log("슈퍼바이저 시작")

        # 세션 초기화
        for name, config in PROJECTS.items():
            state = SessionState(name=name, config=config)
            self.sessions[name] = state

        self._load_session_ids()

        # AsyncClient 먼저 생성 (폴링에 필요)
        self._ahttp = httpx.AsyncClient(timeout=35)

        # 폴링 + 유틸리티 루프 즉시 시작 (연결 전에도 메시지 수신 가능)
        tasks = []
        for name, state in self.sessions.items():
            tasks.append(asyncio.create_task(self._bot_poll_loop(state)))
        tasks.append(asyncio.create_task(self._restart_flag_loop()))
        tasks.append(asyncio.create_task(self._health_check_loop()))
        tasks.append(asyncio.create_task(self._watchdog_loop()))

        # 세션 순차 연결 (동시 생성 시 프로세스 폭주로 initialize 타임아웃)
        for name, state in self.sessions.items():
            await self._connect_session(state)
            if state.connected:
                await asyncio.sleep(10)  # MCP 초기화 안정화 대기

        # 세션 루프 시작 (연결된 세션만 처리, 미연결은 자동 재연결)
        for name, state in self.sessions.items():
            tasks.append(asyncio.create_task(self._session_loop(state)))

        # 시작 알림
        for state in self.sessions.values():
            send_telegram(f"[SV] 시작 완료 — 메시지 수신 준비됨", state.config["bot_token"], notify=True)
        self._write_status()

        log("모든 루프 시작됨")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                log(f"task[{i}] 에러로 종료: {r}")

    async def _flush_pending_updates(self, state: SessionState):
        """pause 중 쌓인 메시지를 버리고 offset을 최신으로 맞춤"""
        bot_token = state.config["bot_token"]
        bot_id = state.config["bot_id"]
        try:
            r = await self._ahttp.get(
                f"https://api.telegram.org/bot{bot_token}/getUpdates",
                params={"timeout": 0}, timeout=10,
            )
            results = r.json().get("result", [])
            if results:
                last_id = max(u["update_id"] for u in results)
                await self._ahttp.get(
                    f"https://api.telegram.org/bot{bot_token}/getUpdates",
                    params={"offset": last_id + 1, "timeout": 0}, timeout=10,
                )
                self._update_ids[bot_id] = last_id
                log(f"{state.name}: wakeup flush — {len(results)}개 메시지 스킵")
        except Exception as e:
            log(f"{state.name}: wakeup flush 실패: {e}")

    async def _safe_disconnect(self, client, name: str):
        """disconnect를 타임아웃 포함으로 안전하게 실행 (fire-and-forget용)"""
        try:
            await asyncio.wait_for(client.disconnect(), timeout=10)
            log(f"{name}: disconnect 완료")
        except BaseException as e:
            log(f"{name}: disconnect 에러 (무시): {e}")

    async def _connect_session(self, state: SessionState, mode: str = "resume"):
        try:
            mcp_servers = {}
            mcp_json_path = state.config.get("mcp_json")
            if mcp_json_path and os.path.exists(mcp_json_path):
                with open(mcp_json_path, "r", encoding="utf-8") as f:
                    mcp_data = json.load(f)
                mcp_servers = mcp_data.get("mcpServers", {})
                # 폴링하는 telegram MCP만 제외 (sender는 유지)
                exclude = {"telegram", "telegram-crossword", "telegram-nemonemo"}
                mcp_servers = {
                    k: v for k, v in mcp_servers.items()
                    if k not in exclude and not k.startswith("telegram_")
                }

            options = ClaudeCodeOptions(
                permission_mode="bypassPermissions",
                cwd=state.config["cwd"],
                mcp_servers=mcp_servers,
                max_turns=50,
            )

            # reset 모드: 컨텍스트 초기화 (새 대화)
            if mode == "reset":
                state.session_id = None
                log(f"{state.name}: reset 모드 (새 대화)")
            else:
                # resume/new 모두 기존 컨텍스트 유지
                if state.session_id:
                    options.resume = state.session_id
                    log(f"{state.name}: {mode} 모드 (session_id={state.session_id[:16]}...)")
                else:
                    options.continue_conversation = True
                    log(f"{state.name}: continue 폴백 (session_id 없음)")


            state.client = ClaudeSDKClient(options)
            await asyncio.wait_for(state.client.connect(None), timeout=120)
            state.connected = True
            state.error_count = 0
            state.start_time = time.time()
            state.query_count = 0
            log(f"{state.name}: SDK 세션 연결 완료 (mode={mode})")
            send_telegram(f"[SV] {state.name}: 연결 완료", state.config["bot_token"], notify=True)
        except Exception as e:
            if mode != "reset":
                log(f"{state.name}: {mode} 실패 ({e}), reset 모드로 재시도")
                state.session_id = None
                await self._connect_session(state, mode="reset")
                return
            log(f"{state.name}: SDK 연결 실패: {e}")
            state.connected = False
            state.error_count += 1

    async def _ensure_ask_client(self) -> bool:
        """ask 전용 SDK 클라이언트를 생성/재사용. 성공 시 True."""
        if self._ask_client is not None:
            return True
        try:
            options = ClaudeCodeOptions(
                permission_mode="bypassPermissions",
                cwd=SUPERVISOR_DIR,
                max_turns=5,
            )
            self._ask_client = ClaudeSDKClient(options)
            await asyncio.wait_for(self._ask_client.connect(None), timeout=60)
            log("ask 세션 연결 완료")
            return True
        except Exception as e:
            log(f"ask 세션 연결 실패: {e}")
            self._ask_client = None
            return False

    async def _handle_ask(self, question: str, bot_token: str):
        """ask 명령 비동기 처리."""
        if self._ask_busy:
            send_telegram("[SV] /ask 처리 중입니다. 잠시 후 다시 시도하세요.", bot_token)
            return
        self._ask_busy = True
        try:
            if not await self._ensure_ask_client():
                send_telegram("[SV] ask 세션 연결 실패", bot_token)
                return
            send_telegram(f"[SV] 질문 중...", bot_token)
            await self._ask_client.query(question)
            answer_parts = []
            async for msg in self._ask_client.receive_messages():
                if msg is None:
                    continue
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if hasattr(block, "text") and block.text.strip():
                            answer_parts.append(block.text.strip())
                elif isinstance(msg, ResultMessage):
                    break
            answer = "\n".join(answer_parts) if answer_parts else "(빈 응답)"
            if len(answer) > 3900:
                answer = answer[:3900] + "\n... (잘림)"
            send_telegram(f"[SV] Claude:\n{answer}", bot_token)
        except Exception as e:
            log(f"ask 처리 실패: {e}")
            send_telegram(f"[SV] ask 오류: {e}", bot_token)
            # 세션 초기화
            self._ask_client = None
        finally:
            self._ask_busy = False

    async def _restart_session(self, state: SessionState, reason: str, mode: str = "resume"):
        if state.restarting:
            log(f"{state.name}: 이미 재시작 진행 중, 스킵 (사유: {reason})")
            return

        now = time.time()
        state.restart_history = [ts for ts in state.restart_history if now - ts < RESTART_WINDOW]
        if len(state.restart_history) >= MAX_RESTARTS_PER_WINDOW:
            oldest = min(state.restart_history) if state.restart_history else now
            wait_remaining = int(RESTART_WINDOW - (now - oldest))
            if wait_remaining > 0:
                msg = f"[WARN] {state.name}: 재시작 한도 초과 ({MAX_RESTARTS_PER_WINDOW}회/{RESTART_WINDOW//60}분)\n사유: {reason}\n{wait_remaining}초 후 자동 재시도"
                log(msg)
                if now - state.last_notify_time > 300:
                    _notify_all(msg)
                    state.last_notify_time = now
                return

        state.restarting = True
        try:
            log(f"{state.name}: 재시작 시도 (사유: {reason})")
            send_telegram(f"[SV] {state.name}: {reason} → 재시작", state.config["bot_token"])

            # 재시작 전 상태 기록
            state.was_busy_before_restart = state.busy
            state.last_restart_mode = mode

            # client 참조 해제 (disconnect는 별도 태스크에서 불가 — cancel scope 제약)
            # GC가 프로세스 종료 시 정리
            state.client = None
            state.connected = False
            state.busy = False

            await asyncio.sleep(3)

            # reconnect
            await self._connect_session(state, mode=mode)
            state.restart_history.append(now)
            state.restart_count += 1
            self._write_status()
            if state.connected:
                send_telegram(f"[SV] {state.name}: 재시작 완료, 메시지 수신 준비됨", state.config["bot_token"], notify=True)
        finally:
            state.restarting = False

    async def _restart_flag_loop(self):
        while not self._shutdown:
            try:
                await asyncio.sleep(1)

                # supervisor 자체 재시작 flag 체크
                sv_flag = Path(TELEGRAM_DIR) / "restart_request_supervisor.flag"
                if sv_flag.exists():
                    mode = "resume"
                    try:
                        content = sv_flag.read_text(encoding="utf-8").strip()
                        if content in ("resume", "reset"):
                            mode = content
                    except Exception:
                        pass
                    sv_flag.unlink(missing_ok=True)
                    log(f"supervisor 자체 재시작 flag 감지 (mode={mode}) → 프로세스 종료")
                    _notify_all(f"[SV] 자체 재시작 요청 (mode={mode})")
                    self._shutdown = True
                    os._exit(0)  # wrapper가 자동 재시작

                for name, state in self.sessions.items():
                    # pause flag 체크
                    pause_path = Path(TELEGRAM_DIR) / f"telegram_pause_{name}.flag"
                    if pause_path.exists() and not state.paused:
                        # pause 진입 — client 참조만 해제 (disconnect는 GC에 맡김)
                        log(f"{name}: pause flag 감지 → pause 설정")
                        state.paused = True
                        state.connected = False
                        state.busy = False
                        state.client = None
                        send_telegram(f"[SV] {name}: 일시정지됨 (CLI 사용 가능)", state.config["bot_token"])
                        self._write_status()
                    elif not pause_path.exists() and state.paused:
                        # wakeup (flag 삭제됨) — pause 중 쌓인 메시지 flush 후 reconnect
                        log(f"{name}: pause flag 삭제됨 → SDK reconnect")
                        state.paused = False
                        await self._flush_pending_updates(state)
                        await self._connect_session(state, mode="resume")
                        send_telegram(f"[SV] {name}: 일시정지 해제, SDK 재연결", state.config["bot_token"])
                        self._write_status()

                    # restart flag 체크
                    flag_path = Path(TELEGRAM_DIR) / f"restart_request_{name}.flag"
                    if not flag_path.exists():
                        continue
                    mode = "resume"
                    try:
                        content = flag_path.read_text(encoding="utf-8").strip()
                        if content in ("new", "resume", "reset"):
                            mode = content
                    except Exception:
                        pass
                    flag_path.unlink(missing_ok=True)
                    log(f"{name}: restart_request flag 감지 (mode={mode})")
                    await self._restart_session(state, f"flag 요청 (mode={mode})", mode=mode)
            except asyncio.CancelledError:
                raise
            except BaseException as e:
                log(f"restart_flag_loop 에러: {e}")
                await asyncio.sleep(5)

    def _assess_health(self, state: SessionState) -> str:
        if state.paused:
            return "PAUSED"
        if not state.connected or state.client is None:
            return "DEAD"
        elapsed = time.time() - state.start_time
        if elapsed < HEALTH_CHECK_INTERVAL:
            return "OK"
        if state.busy and state.busy_since > 0:
            busy_duration = time.time() - state.busy_since
            if busy_duration > STUCK_THRESHOLD:
                return "STUCK"
        return "OK"

    async def _health_check_loop(self):
        # 시작 후 2분 grace period
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)
        while not self._shutdown:
            try:
                for name, state in self.sessions.items():
                    if self._shutdown:
                        return
                    status = self._assess_health(state)
                    if status == "PAUSED":
                        continue
                    elif status == "DEAD":
                        await self._restart_session(state, "DEAD")
                    elif status == "STUCK":
                        await self._restart_session(state, "STUCK (30분+ busy)")
                self._write_status()
            except asyncio.CancelledError:
                raise
            except BaseException as e:
                log(f"health_check_loop 에러: {e}")
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)

    def _save_session_ids(self):
        """session_id를 파일에 저장 (재시작 시 복원용)."""
        data = {}
        for name, state in self.sessions.items():
            if state.session_id:
                data[name] = state.session_id
        try:
            with open(SESSION_IDS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _load_session_ids(self):
        """저장된 session_id를 복원."""
        try:
            with open(SESSION_IDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name, sid in data.items():
                if name in self.sessions and sid:
                    self.sessions[name].session_id = sid
                    log(f"{name}: session_id 복원됨 ({sid[:16]}...)")
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        except Exception as e:
            log(f"session_id 복원 실패: {e}")

    def _write_status(self):
        now = time.time()
        data = {
            "pid": os.getpid(),
            "uptime": int(now - self._start_time),
            "ts": now,
            "sessions": {},
        }
        for name, state in self.sessions.items():
            data["sessions"][name] = {
                "connected": state.connected,
                "busy": state.busy,
                "paused": state.paused,
                "status": "PAUSED" if state.paused else self._assess_health(state),
                "session_id": state.session_id[:16] if state.session_id else None,
                "restart_count": state.restart_count,
                "query_count": state.query_count,
                "error_count": state.error_count,
                "start_time": state.start_time,
            }
        try:
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    async def _watchdog_loop(self):
        while not self._shutdown:
            await asyncio.sleep(30)
            self._watchdog_ts = time.time()

    def _start_watchdog_thread(self):
        def _watchdog():
            while not self._shutdown:
                time.sleep(30)
                age = time.time() - self._watchdog_ts
                if age > 300:
                    log(f"WATCHDOG: asyncio 루프 {int(age)}초 무응답, 강제 종료")
                    os._exit(1)
        t = threading.Thread(target=_watchdog, daemon=True)
        t.start()

    def _handle_command(self, text: str, bot_token: str) -> bool:
        """슈퍼바이저 명령어 처리. 처리했으면 True 반환."""
        return handle_command(self, text, bot_token)

    def _find_session_by_token(self, bot_token: str) -> str | None:
        for name, state in self.sessions.items():
            if state.config["bot_token"] == bot_token:
                return name
        return None

    def _get_usage(self) -> str:
        return _get_usage(self._http)

    async def _download_photo(self, msg: dict, bot_token: str, name: str) -> str:
        """텔레그램 이미지를 다운로드하여 로컬 경로 반환."""
        photos = msg.get("photo", [])
        if not photos:
            return ""
        # 가장 큰 해상도 선택
        photo = photos[-1]
        file_id = photo.get("file_id", "")
        if not file_id:
            return ""
        try:
            # getFile API로 파일 경로 조회
            url = f"https://api.telegram.org/bot{bot_token}/getFile"
            r = await self._ahttp.post(url, json={"file_id": file_id}, timeout=10)
            data = r.json()
            if not data.get("ok"):
                log(f"{name}: getFile 실패: {data}")
                return ""
            file_path = data["result"]["file_path"]
            # 다운로드
            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
            r = await self._ahttp.get(download_url, timeout=30)
            # 로컬 저장
            save_dir = os.path.join(LOGS_DIR, "images")
            os.makedirs(save_dir, exist_ok=True)
            ext = os.path.splitext(file_path)[1] or ".jpg"
            save_path = os.path.join(save_dir, f"{name}_{int(time.time())}{ext}")
            with open(save_path, "wb") as f:
                f.write(r.content)
            log(f"{name}: 이미지 다운로드 완료: {save_path}")
            return save_path
        except Exception as e:
            log(f"{name}: 이미지 다운로드 실패: {e}")
            return ""

    @staticmethod
    def _tool_summary(tool_name: str, tool_input: dict) -> str:
        """도구 호출을 짧은 이름으로 요약"""
        # MCP 도구명 축약 (mcp__ai-chat__ask → ai-chat.ask)
        short = tool_name
        if short.startswith("mcp__"):
            parts = short[5:].split("__", 1)
            short = ".".join(parts) if len(parts) > 1 else parts[0]
        path = (tool_input.get("file_path") or tool_input.get("path")
                or tool_input.get("pattern") or tool_input.get("command", "")[:60])
        if path:
            # 긴 경로는 파일명만
            if len(path) > 40:
                path = "..." + path[-35:]
            return f"{short}: {path}"
        return short

    @staticmethod
    def _format_tool_line(tool_lines: list) -> str:
        """도구 호출 목록을 컴팩트한 한 줄로 포맷"""
        # "🔧 Read: a.py", "🔧 Grep: b.py" → "─ 🔧 Read: a.py → Grep: b.py"
        names = [t.replace("\U0001f527 ", "") for t in tool_lines]
        return "\u2500 \U0001f527 " + " \u2192 ".join(names)

    @staticmethod
    def _stabilize_markdown(text: str) -> str:
        """edit 전 미닫힌 코드블록을 임시로 닫아 마크다운 깨짐 방지."""
        if text.count("```") % 2 == 1:
            text += "\n```"
        return text

    def _should_auto_resume(self, state: SessionState) -> bool:
        """자동 재개 여부를 판단."""
        # reset 모드면 재개 안 함
        if state.last_restart_mode == "reset":
            log(f"{state.name}: reset 모드 → 자동 재개 스킵")
            return False
        # 재시작 전 busy가 아니었으면 재개 불필요
        if not state.was_busy_before_restart:
            log(f"{state.name}: 재시작 전 대기 상태 → 자동 재개 스킵")
            return False
        # session_id 없으면 맥락 유실 → 재개 위험
        if not state.session_id:
            log(f"{state.name}: session_id 없음 (맥락 유실) → 자동 재개 스킵")
            return False
        # resume_count 초과
        if state.resume_count >= 2:
            log(f"{state.name}: 자동 재개 {state.resume_count}회 초과 → 중단")
            send_telegram(
                f"\u26a0\ufe0f {state.name}: 자동 재개 2회 실패, 중단했습니다. 수동 확인 필요.",
                state.config["bot_token"], state.name,
            )
            state.resume_count = 0
            return False
        return True

    async def _session_loop(self, state: SessionState):
        # 자동 재개: 조건 충족 시에만
        if state.connected and not state.message_queue.qsize():
            if self._should_auto_resume(state):
                state.resume_count += 1
                log(f"{state.name}: 자동 재개 ({state.resume_count}/2) — AI에게 판단 위임")
                await state.message_queue.put({
                    "text": "이전에 하던 작업이 있으면 이어서 해줘. 없으면 대기해줘.",
                    "msg_id": 0,
                    "auto_resume": True,
                })
            else:
                log(f"{state.name}: 연결 완료 — 대기 모드")

        while not self._shutdown:
            try:
                msg_data = await asyncio.wait_for(
                    state.message_queue.get(), timeout=60
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                continue
            except BaseException:
                continue

            if state.paused or not state.client:
                log(f"{state.name}: paused/미연결 상태, 큐 메시지 무시")
                continue

            if not state.connected:
                await self._restart_session(state, "세션 미연결")
                if not state.connected or not state.client:
                    send_telegram(
                        f"세션 연결 실패, 메시지 처리 불가: {msg_data['text']}",
                        state.config["bot_token"], state.name,
                    )
                    continue

            state.busy = True
            state.busy_since = time.time()
            text = msg_data["text"]
            is_auto_resume = msg_data.get("auto_resume", False)
            msg_id = msg_data.get("msg_id", 0)

            # 사용자 메시지 → resume_count 리셋
            if not is_auto_resume and state.resume_count > 0:
                state.resume_count = 0

            log(f"{state.name}: 메시지 처리 시작: {text[:50]}")
            # 처리 시작 알림은 수신 확인(✔️)으로 대체됨

            try:
                client = state.client
                if not client:
                    continue
                await client.query(text)
                live_msg_id = 0  # 현재 editMessage 대상
                live_lines = []  # 현재 메시지에 쌓인 텍스트
                tool_lines = []  # 도구 호출 임시 버퍼 (텍스트 오면 정리)
                last_tool_name = ""  # 마지막 도구명 (ToolResult 판별용)
                msg_count = 0
                last_edit = 0.0
                edit_interval = 1.0  # 적응형 edit 간격 (초)
                consecutive_edit_fails = 0  # 연속 edit 실패 횟수
                bot_token = state.config["bot_token"]

                async for msg in client.receive_messages():
                    if msg is None:
                        continue
                    msg_count += 1

                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            block_type = type(block).__name__
                            if hasattr(block, "text") and block.text.strip():
                                # TextBlock — 텍스트 응답 도착하면 도구 요약 정리
                                if tool_lines:
                                    live_lines.append(self._format_tool_line(tool_lines))
                                    tool_lines = []
                                live_lines.append(block.text)
                                log(f"{state.name}: [block] TextBlock ({len(block.text)}자)")
                            elif block_type == "ToolUseBlock":
                                tool_name = getattr(block, "name", "tool")
                                tool_input = getattr(block, "input", {})
                                last_tool_name = tool_name
                                summary = self._tool_summary(tool_name, tool_input)
                                tool_lines.append(f"\U0001f527 {summary}")
                                log(f"{state.name}: [block] ToolUse: {summary}")
                            elif block_type == "ThinkingBlock":
                                log(f"{state.name}: [block] Thinking (skip)")
                                continue
                            else:
                                log(f"{state.name}: [block] {block_type} (skip)")
                                continue

                            # 실시간 전송/수정
                            now = time.time()
                            display = list(live_lines)
                            if tool_lines:
                                display.append(self._format_tool_line(tool_lines))
                            content = "\n".join(display)

                            # 새 메시지 분리 기준: 10초+ 간격 또는 2000자 초과
                            need_new_msg = (
                                live_msg_id and (
                                    now - last_edit >= 10.0 or
                                    len(content) > 2000
                                )
                            )
                            if need_new_msg:
                                # 기존 메시지 마무리 후 새 메시지 시작
                                prev = "\n".join(live_lines[:-1]) if len(live_lines) > 1 else ""
                                if prev:
                                    await async_edit_telegram(self._ahttp, prev, live_msg_id, bot_token, state.name)
                                new_start = live_lines[-1] if live_lines else ""
                                live_msg_id = await async_send_telegram(self._ahttp, new_start, bot_token, state.name)
                                live_lines = [new_start] if new_start else []
                                tool_lines = []
                                last_edit = now
                            elif not live_msg_id:
                                live_msg_id = await async_send_telegram(self._ahttp, content, bot_token, state.name)
                                last_edit = now
                            elif now - last_edit >= edit_interval:
                                # 4096자 한도 대비 여유 (prefix + 마진)
                                max_len = 4096 - len(f"[{state.name}] ") - 50
                                stable_content = self._stabilize_markdown(content)
                                if len(content) > max_len:
                                    prev = "\n".join(live_lines[:-1]) if len(live_lines) > 1 else "\n".join(live_lines)
                                    await async_edit_telegram(self._ahttp, self._stabilize_markdown(prev), live_msg_id, bot_token, state.name)
                                    new_start = live_lines[-1] if live_lines else ""
                                    live_msg_id = await async_send_telegram(self._ahttp, new_start, bot_token, state.name)
                                    live_lines = [new_start] if new_start else []
                                    tool_lines = []
                                else:
                                    ok = await async_edit_telegram(self._ahttp, stable_content, live_msg_id, bot_token, state.name)
                                    if not ok:
                                        consecutive_edit_fails += 1
                                        if consecutive_edit_fails >= 3:
                                            # rate limit 대응: 간격 증가
                                            edit_interval = min(edit_interval * 2, 5.0)
                                            consecutive_edit_fails = 0
                                        live_msg_id = await async_send_telegram(self._ahttp, stable_content, bot_token, state.name)
                                    else:
                                        consecutive_edit_fails = 0
                                        # 성공 시 간격 점진 복원
                                        if edit_interval > 1.0:
                                            edit_interval = max(edit_interval - 0.5, 1.0)
                                last_edit = now

                    elif isinstance(msg, UserMessage):
                        # ToolResult 처리 — ai-chat 결과는 전문, 나머지는 요약
                        result_text = ""
                        for block in msg.content:
                            if hasattr(block, "text") and block.text:
                                result_text = block.text.strip()
                                break
                            elif hasattr(block, "content") and isinstance(block.content, str):
                                result_text = block.content.strip()
                                break
                        if result_text:
                            is_ai_chat = last_tool_name.startswith("mcp__ai_chat__") or last_tool_name.startswith("mcp__ai-chat__")
                            if is_ai_chat:
                                # ai-chat 결과는 별도 새 메시지로 분리
                                if live_msg_id:
                                    # live_lines가 비어있어도 tool_lines로 이전 메시지 마무리
                                    prev_content = "\n".join(live_lines) if live_lines else ""
                                    if tool_lines:
                                        tl = self._format_tool_line(tool_lines)
                                        prev_content = f"{prev_content}\n{tl}" if prev_content else tl
                                    if prev_content:
                                        await async_edit_telegram(self._ahttp, prev_content, live_msg_id, bot_token, state.name)
                                    tool_lines = []
                                    live_lines = []
                                    live_msg_id = None
                                # JSON {"result":"..."} 파싱
                                display_text = result_text
                                try:
                                    parsed = json.loads(result_text)
                                    if isinstance(parsed, dict) and "result" in parsed:
                                        display_text = parsed["result"]
                                except (json.JSONDecodeError, TypeError):
                                    pass
                                live_lines.append(f"\U0001f4ac {display_text}")
                                log(f"{state.name}: [result] ai-chat ({len(result_text)}자)")
                            elif len(result_text) <= 500:
                                if tool_lines:
                                    live_lines.append(self._format_tool_line(tool_lines))
                                    tool_lines = []
                                live_lines.append(result_text)
                                log(f"{state.name}: [result] short ({len(result_text)}자)")
                            else:
                                snippet = result_text[:100].replace("\n", " ")
                                # 마지막 도구 라인에 결과 요약 붙이기
                                if tool_lines:
                                    tool_lines[-1] += f" ({len(result_text)}자)"
                                log(f"{state.name}: [result] long ({len(result_text)}자)")

                            # 실시간 업데이트
                            now = time.time()
                            display = list(live_lines)
                            if tool_lines:
                                display.append(self._format_tool_line(tool_lines))
                            content = "\n".join(display)
                            if not live_msg_id:
                                live_msg_id = await async_send_telegram(self._ahttp, self._stabilize_markdown(content), bot_token, state.name)
                                last_edit = now
                            elif now - last_edit >= edit_interval:
                                stable_content = self._stabilize_markdown(content)
                                ok = await async_edit_telegram(self._ahttp, stable_content, live_msg_id, bot_token, state.name)
                                if not ok:
                                    consecutive_edit_fails += 1
                                    if consecutive_edit_fails >= 3:
                                        edit_interval = min(edit_interval * 2, 5.0)
                                        consecutive_edit_fails = 0
                                    live_msg_id = await async_send_telegram(self._ahttp, stable_content, bot_token, state.name)
                                else:
                                    consecutive_edit_fails = 0
                                    if edit_interval > 1.0:
                                        edit_interval = max(edit_interval - 0.5, 1.0)
                                last_edit = now

                    elif isinstance(msg, ResultMessage):
                        if hasattr(msg, "session_id") and msg.session_id:
                            state.session_id = msg.session_id
                            self._save_session_ids()
                        break

                # 최종 업데이트 (HTML 변환 적용)
                if tool_lines:
                    live_lines.append(self._format_tool_line(tool_lines))
                if live_lines:
                    content = "\n".join(live_lines)
                    html_content = _md_to_telegram_html(content)
                    # 분할이 필요한 긴 메시지는 새 메시지로 전송
                    chunks = _split_message(html_content)
                    if live_msg_id:
                        ok = await async_edit_telegram(self._ahttp, chunks[0], live_msg_id, bot_token, state.name, use_html=True)
                        if not ok:
                            await async_send_telegram(self._ahttp, chunks[0], bot_token, state.name, use_html=True)
                        # 추가 청크가 있으면 새 메시지로 전송
                        for chunk in chunks[1:]:
                            await async_send_telegram(self._ahttp, chunk, bot_token, state.name, use_html=True)
                    else:
                        for chunk in chunks:
                            await async_send_telegram(self._ahttp, chunk, bot_token, state.name, use_html=True)
                    log(f"{state.name}: 최종 전송 ({len(content)}자, {len(chunks)}청크)")
                else:
                    log(f"{state.name}: 빈 응답")

                log(f"{state.name}: 처리 완료")

                # 처리 완료 리액션 (✅)
                msg_id = msg_data.get("msg_id")
                if msg_id:
                    await async_react(self._ahttp, bot_token, msg_id, "\u2705")

                # 처리 완료 후 offset 확정 (재시작 시 미처리 메시지 재수신 보장)
                processed_update_id = msg_data.get("update_id", 0)
                if processed_update_id:
                    bot_id = state.config["bot_id"]
                    self._update_ids[bot_id] = max(
                        self._update_ids.get(bot_id, 0), processed_update_id
                    )

                state.error_count = 0
                state.query_count += 1
                # 정상 완료 → resume_count 리셋
                if state.resume_count > 0:
                    log(f"{state.name}: 정상 완료 → resume_count 리셋 ({state.resume_count} → 0)")
                    state.resume_count = 0

                # 주기적 세션 리셋 체크
                session_age = time.time() - state.start_time
                if state.query_count >= SESSION_RESET_QUERIES or session_age >= SESSION_RESET_HOURS * 3600:
                    log(f"{state.name}: 자동 리셋 (Q={state.query_count}, {int(session_age/3600)}h)")
                    await self._restart_session(state, f"자동 리셋 (Q={state.query_count})", mode="reset")

            except Exception as e:
                log(f"{state.name}: 처리 에러: {e}")
                state.error_count += 1
                send_telegram(
                    f"처리 에러: {e}",
                    state.config["bot_token"], state.name,
                )
                if state.error_count >= 3:
                    await self._restart_session(state, f"연속 에러 {state.error_count}회")
            finally:
                state.busy = False
                state.busy_since = 0.0

    async def _bot_poll_loop(self, state: SessionState):
        """봇별 독립 폴링 태스크 — 각 봇이 병렬로 long polling"""
        name = state.name
        bot_token = state.config["bot_token"]
        bot_id = state.config["bot_id"]

        # offset 초기화
        try:
            r = await self._ahttp.get(
                f"https://api.telegram.org/bot{bot_token}/getUpdates",
                params={"timeout": 0}, timeout=10,
            )
            results = r.json().get("result", [])
            if results:
                last_id = max(u["update_id"] for u in results)
                await self._ahttp.get(
                    f"https://api.telegram.org/bot{bot_token}/getUpdates",
                    params={"offset": last_id + 1, "timeout": 0}, timeout=10,
                )
                self._update_ids[bot_id] = last_id
            else:
                self._update_ids[bot_id] = 0
            log(f"{name}: offset 초기화 = {self._update_ids[bot_id]} (flushed {len(results)})")
        except Exception as e:
            log(f"{name}: offset 초기화 실패: {e}")
            self._update_ids[bot_id] = 0

        error_count = 0
        while not self._shutdown:
            if state.paused:
                await asyncio.sleep(2)
                continue

            last_id = self._update_ids.get(bot_id, 0)
            try:
                r = await self._ahttp.get(
                    f"https://api.telegram.org/bot{bot_token}/getUpdates",
                    params={
                        "offset": last_id + 1,
                        "timeout": 25,
                        "allowed_updates": ["message"],
                    },
                    timeout=35,
                )
                r.raise_for_status()
                updates = r.json().get("result", [])
                for u in updates:
                    update_id = u["update_id"]
                    msg = u.get("message", {})
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if chat_id != CHAT_ID:
                        self._update_ids[bot_id] = update_id
                        continue
                    msg_date = msg.get("date", 0)
                    if msg_date < self._start_time:
                        log(f"{name}: 오래된 메시지 스킵 (date={msg_date})")
                        self._update_ids[bot_id] = update_id
                        continue
                    msg_id = msg.get("message_id", 0)
                    text = msg.get("text", "")

                    # 이미지 메시지 처리
                    if not text and msg.get("photo"):
                        photo_path = await self._download_photo(msg, bot_token, name)
                        if photo_path:
                            caption = msg.get("caption", "")
                            text = f"이 이미지를 확인해줘: {photo_path}"
                            if caption:
                                text = f"{caption}\n\n이미지: {photo_path}"

                    if not text:
                        self._update_ids[bot_id] = update_id
                        continue

                    if self._handle_command(text, bot_token):
                        log(f"{name}: 명령어 처리: {text}")
                        self._update_ids[bot_id] = update_id
                        continue

                    sender = msg.get("from", {}).get("first_name", "")
                    full_text = f"{sender}: {text}"

                    # 중복 메시지 제거 (message_id 기반)
                    msg_key = f"{name}_{msg_id}"
                    if msg_key in self._last_msg_map:
                        self._update_ids[bot_id] = update_id
                        continue
                    self._last_msg_map[msg_key] = time.time()
                    # 오래된 항목 정리 (100개 초과 시)
                    if len(self._last_msg_map) > 100:
                        cutoff = time.time() - 300
                        self._last_msg_map = {k: v for k, v in self._last_msg_map.items() if v > cutoff}

                    await state.message_queue.put({
                        "text": full_text,
                        "msg_id": msg_id,
                        "update_id": update_id,
                    })
                    # 큐에 넣은 즉시 offset 갱신 (재폴링 방지)
                    self._update_ids[bot_id] = update_id
                    # 수신 확인 (fire-and-forget) — 원문 포함
                    ack_text = f"\u2714\ufe0f {text[:50]}"
                    asyncio.create_task(async_send_telegram(self._ahttp, ack_text, bot_token, name, reply_to=msg_id))
                    log(f"{name}: 메시지 수신: {text[:50]}")
                if error_count > 0:
                    error_count = 0
            except Exception as e:
                error_count += 1
                if error_count % 10 == 1:
                    log(f"{name}: 폴링 에러 #{error_count}: {e}")
                await asyncio.sleep(min(2 ** min(error_count, 5), 30))

    async def shutdown(self):
        self._shutdown = True
        if self._ahttp:
            await self._ahttp.aclose()
        # client 참조만 해제 (disconnect는 프로세스 종료 시 자동 정리)
        for name, state in self.sessions.items():
            state.client = None
            state.connected = False
        self._write_status()
        _release_lock()
        log("슈퍼바이저 종료")


async def main():
    os.makedirs(LOGS_DIR, exist_ok=True)

    existing_pid = _find_existing_supervisor()
    if existing_pid:
        log(f"이미 실행 중인 슈퍼바이저 있음 (PID={existing_pid}), 종료")
        print(f"이미 슈퍼바이저가 실행 중입니다 (PID={existing_pid}).")
        sys.exit(42)  # wrapper가 중복 실행 감지용 코드로 인식

    _write_lock()
    hub = Supervisor()
    hub._start_watchdog_thread()

    def on_signal(sig, frame):
        hub._shutdown = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    try:
        await hub.start()
    except KeyboardInterrupt:
        pass
    finally:
        await hub.shutdown()

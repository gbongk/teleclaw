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

# monkey-patch: 알 수 없는 메시지 타입 (rate_limit_event 등) 무시
import claude_code_sdk._internal.message_parser as _mp
_original_parse = _mp.parse_message
def _patched_parse(data):
    try:
        return _original_parse(data)
    except Exception:
        return None
_mp.parse_message = _patched_parse

from .config import (
    PROJECTS, CHAT_ID, SUPERVISOR_DIR, LOGS_DIR, LOG_FILE,
    STATUS_FILE, SESSION_IDS_FILE, DATA_DIR, TELEGRAM_DIR,
    HEALTH_CHECK_INTERVAL, STUCK_THRESHOLD,
    MAX_RESTARTS_PER_WINDOW, RESTART_WINDOW,
    SESSION_RESET_QUERIES, SESSION_RESET_HOURS,
    AUTO_RESUME_ENABLED, AUTO_RESUME_MODE, AUTO_RESUME_PROMPTS,
)
from .logging_utils import log, _find_existing_supervisor, _write_lock, _release_lock
from .telegram_api import (
    send_telegram, edit_telegram, send_ack,
    _clean_text, _escape_html, _convert_table_to_list,
    _md_to_telegram_html, _split_message,
    async_send_telegram, async_edit_telegram, async_react,
    _notify_all, async_notify_all,
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
        self._fresh_start = True  # 슈퍼바이저 프로세스 시작 직후 (개별 세션 재시작과 구분)

    async def start(self):
        log("슈퍼바이저 시작")
        _notify_all("[HUB] 슈퍼바이저 시작")

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

        # 세션 병렬 연결 (다운타임 최소화, pause 세션 제외)
        async def _connect_and_init(state):
            pause_flag = Path(TELEGRAM_DIR) / f"pause_{state.name}.flag"
            if pause_flag.exists():
                log(f"{state.name}: PAUSED — 연결 스킵")
                return
            await self._connect_session(state)
            if state.connected:
                await self._wait_mcp_ready(state, timeout=5)
                send_telegram(f"[SV] 시작 완료 — 메시지 수신 준비됨", state.config["bot_token"], notify=True)
                log(f"{state.name}: 세션 루프 즉시 시작")

        await asyncio.gather(
            *[_connect_and_init(s) for s in self.sessions.values()],
            return_exceptions=True,
        )

        # 모든 세션 루프 시작 (연결 여부 무관 — 미연결은 자동 재연결)
        for name, state in self.sessions.items():
            tasks.append(asyncio.create_task(self._session_loop(state)))

        self._write_status()

        connected = [n for n, s in self.sessions.items() if s.connected]
        elapsed = int(time.time() - self._start_time)
        await async_notify_all(self._ahttp, f"[HUB] 초기화 완료 ({elapsed}초) — {', '.join(connected)} 연결됨")
        log("모든 루프 시작됨")

        # 슈퍼바이저 시작 시에는 자동 재개 안 함
        # (세션이 아직 불안정할 수 있고, was_busy_before_restart도 없음)
        self._fresh_start = False
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                log(f"task[{i}] 에러로 종료: {r}")
                await async_notify_all(self._ahttp, f"[HUB] task[{i}] 에러: {r}")


    async def _safe_disconnect(self, client, name: str):
        """프로세스를 직접 종료. client.disconnect()는 anyio cancel scope 충돌로 CPU 100% 유발하므로 호출하지 않음."""
        try:
            transport = getattr(client, "_transport", None)
            proc = getattr(transport, "_process", None) if transport else None
            if proc and proc.returncode is None:
                proc.terminate()
                log(f"{name}: 프로세스 terminate (pid={proc.pid})")
            else:
                log(f"{name}: 프로세스 이미 종료됨")
        except Exception as kill_err:
                log(f"{name}: 프로세스 종료 실패: {kill_err}")

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
            state.last_restart_mode = mode
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

    async def _wait_mcp_ready(self, state: SessionState, timeout: int = 5):
        """MCP 서버 준비 대기. 최소 3초, 최대 timeout초."""
        for i in range(timeout):
            await asyncio.sleep(1)
            if not state.connected or not state.client:
                break
        log(f"{state.name}: MCP 안정화 대기 완료 ({min(timeout, i+1)}초)")

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

    async def _restart_session(self, state: SessionState, reason: str, mode: str = "resume", force: bool = False, no_resume: bool = False):
        if state.restarting:
            log(f"{state.name}: 이미 재시작 진행 중, 스킵 (사유: {reason})")
            return

        now = time.time()
        state.restart_history = [ts for ts in state.restart_history if now - ts < RESTART_WINDOW]
        if not force and len(state.restart_history) >= MAX_RESTARTS_PER_WINDOW:
            oldest = min(state.restart_history) if state.restart_history else now
            wait_remaining = int(RESTART_WINDOW - (now - oldest))
            if wait_remaining > 0:
                msg = f"[WARN] {state.name}: 재시작 한도 초과 ({MAX_RESTARTS_PER_WINDOW}회/{RESTART_WINDOW//60}분)\n사유: {reason}\n{wait_remaining}초 후 자동 재시도"
                log(msg)
                if now - state.last_notify_time > 300:
                    if self._ahttp:
                        await async_notify_all(self._ahttp, msg)
                    else:
                        _notify_all(msg)
                    state.last_notify_time = now
                return

        state.restarting = True
        try:
            log(f"{state.name}: 재시작 시도 (사유: {reason})")
            send_telegram(f"[SV] {state.name}: {reason} → 재시작", state.config["bot_token"])

            # 재시작 전 상태 기록 (STUCK은 busy 강제)
            state.was_busy_before_restart = state.busy or "STUCK" in reason
            state.last_restart_mode = mode

            # client disconnect 후 참조 해제
            old_client = state.client
            state.client = None
            if old_client:
                asyncio.create_task(self._safe_disconnect(old_client, state.name))
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

                # auto-resume: 세션 개별 재시작 시에만
                # reset(new) 또는 슈퍼바이저 초기 시작 시에는 스킵 (start()에서 check 모드로 처리)
                if mode != "new" and not self._fresh_start and AUTO_RESUME_ENABLED and not no_resume and state.message_queue.empty():
                    # 세션 개별 재시작 → 설정된 모드(resume/check) 사용
                    effective_mode = AUTO_RESUME_MODE
                    prompt = AUTO_RESUME_PROMPTS.get(effective_mode)
                    if prompt and self._should_auto_resume(state):
                        state.resume_count += 1
                        log(f"{state.name}: 자동 재개 ({state.resume_count}/2, mode={effective_mode}) — AI에게 판단 위임")
                        await state.message_queue.put({
                            "text": prompt,
                            "msg_id": 0,
                            "auto_resume": True,
                            "retry_count": 0,
                        })
                    elif effective_mode == "none" and self._should_auto_resume(state):
                        log(f"{state.name}: auto-resume mode=none → 프롬프트 없이 대기")
        finally:
            state.restarting = False

    async def _restart_flag_loop(self):
        while not self._shutdown:
            try:
                await asyncio.sleep(1)

                # supervisor 자체 재시작 flag 체크 (5분 쿨다운)
                sv_flag = Path(TELEGRAM_DIR) / "restart_request_supervisor.flag"
                if sv_flag.exists():
                    mode = "resume"
                    force = False
                    try:
                        content = sv_flag.read_text(encoding="utf-8").strip()
                        if content == "force":
                            force = True
                        elif content in ("resume", "reset"):
                            mode = content
                    except Exception:
                        pass
                    sv_flag.unlink(missing_ok=True)
                    cooldown = 300  # 5분
                    elapsed = time.time() - self._start_time
                    if not force and elapsed < cooldown:
                        log(f"supervisor 자체 재시작 flag 무시 (쿨다운: {int(cooldown - elapsed)}초 남음)")
                    else:
                        # busy 세션은 no_resume 마킹 (auto-resume 루프 방지)
                        self._save_session_ids(no_resume_if_busy=True)
                        # busy 세션이 있으면 완료 대기 (최대 60초)
                        busy_sessions = [n for n, s in self.sessions.items() if s.busy]
                        if busy_sessions and not force:
                            log(f"supervisor 자체 재시작 flag 감지 — busy 세션 대기: {', '.join(busy_sessions)}")
                            waited = 0
                            while waited < 60:
                                await asyncio.sleep(2)
                                waited += 2
                                busy_sessions = [n for n, s in self.sessions.items() if s.busy]
                                if not busy_sessions:
                                    break
                            if busy_sessions:
                                log(f"graceful 대기 60초 초과, 강제 종료 (busy: {', '.join(busy_sessions)})")
                        log(f"supervisor 자체 재시작 flag 감지 (mode={mode}, force={force}) → 프로세스 종료")
                        await async_notify_all(self._ahttp, f"[HUB] 자체 재시작 요청 (mode={mode})")
                        self._shutdown = True
                        os._exit(0)  # wrapper가 자동 재시작

                for name, state in self.sessions.items():
                    # restart flag 체크
                    flag_path = Path(TELEGRAM_DIR) / f"restart_request_{name}.flag"
                    if not flag_path.exists():
                        continue
                    mode = "resume"
                    force = False
                    no_resume = False
                    try:
                        content = flag_path.read_text(encoding="utf-8").strip()
                        tokens = [t.strip() for t in content.split(",")]
                        for t in tokens:
                            if t == "force":
                                force = True
                            elif t == "noresume":
                                no_resume = True
                            elif t in ("new", "resume", "reset"):
                                mode = t
                    except Exception:
                        pass
                    flag_path.unlink(missing_ok=True)
                    # restart 요청 시 pause 자동 해제
                    pause_flag = Path(TELEGRAM_DIR) / f"pause_{name}.flag"
                    if pause_flag.exists():
                        pause_flag.unlink(missing_ok=True)
                        log(f"{name}: pause 해제됨 (restart 요청)")
                    # flag 경유 재시작: 사용자 요청이므로 busy 여부와 무관하게 auto-resume 허용
                    # no_resume는 flag 파일에 명시적으로 "noresume"이 있을 때만 적용
                    state.no_resume_before_restart = False  # busy 마킹 초기화
                    log(f"{name}: restart_request flag 감지 (mode={mode}, force={force}, noresume={no_resume})")
                    await self._restart_session(state, f"flag 요청 (mode={mode})", mode=mode, force=force, no_resume=no_resume)
            except asyncio.CancelledError:
                raise
            except BaseException as e:
                log(f"restart_flag_loop 에러: {e}")
                await asyncio.sleep(5)

    def _assess_health(self, state: SessionState) -> str:
        if state.restarting:
            return "OK"
        if not state.connected or state.client is None:
            return "DEAD"
        elapsed = time.time() - state.start_time
        if elapsed < HEALTH_CHECK_INTERVAL:
            return "OK"
        if state.busy and state.busy_since > 0:
            busy_duration = time.time() - state.busy_since
            if busy_duration > STUCK_THRESHOLD:
                return "STUCK"
        # 큐에 메시지가 있는데 busy가 아닌 상태가 5분 이상 지속
        if not state.busy and state.message_queue.qsize() > 0:
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
                    # pause 플래그가 있으면 재시작 스킵
                    pause_flag = Path(TELEGRAM_DIR) / f"pause_{name}.flag"
                    if pause_flag.exists():
                        continue
                    status = self._assess_health(state)
                    if status == "DEAD":
                        await self._restart_session(state, "DEAD")
                    elif status == "STUCK":
                        await self._restart_session(state, "STUCK (30분+ busy)")
                self._write_status()
            except asyncio.CancelledError:
                raise
            except BaseException as e:
                log(f"health_check_loop 에러: {e}")
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)

    def _save_offset(self, bot_id: str, offset: int):
        """폴링 offset을 파일에 원자적으로 저장 (write→rename)."""
        path = os.path.join(DATA_DIR, f"last_offset_{bot_id}.json")
        tmp_path = path + ".tmp"
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(tmp_path, "w") as f:
                json.dump({"offset": offset, "ts": time.time()}, f)
            os.replace(tmp_path, path)
        except Exception:
            pass

    def _load_offset(self, bot_id: str) -> int | None:
        """저장된 offset 복원. 없으면 None."""
        path = os.path.join(DATA_DIR, f"last_offset_{bot_id}.json")
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return data.get("offset")
        except Exception:
            return None

    def _save_session_ids(self, no_resume_if_busy=False):
        """session_id + busy 상태를 파일에 저장 (재시작 시 복원용).
        no_resume_if_busy=True: 슈퍼바이저 자체 재시작 시, busy 세션은 no_resume 마킹."""
        data = {}
        for name, state in self.sessions.items():
            entry = {}
            if state.session_id:
                entry["session_id"] = state.session_id
            entry["was_busy"] = state.busy
            if no_resume_if_busy and state.busy:
                entry["no_resume"] = True
            data[name] = entry
        try:
            with open(SESSION_IDS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _load_session_ids(self):
        """저장된 session_id + busy 상태를 복원."""
        try:
            with open(SESSION_IDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name, val in data.items():
                if name not in self.sessions:
                    continue
                state = self.sessions[name]
                # 하위 호환: 문자열이면 session_id만
                if isinstance(val, str):
                    if val:
                        state.session_id = val
                        log(f"{name}: session_id 복원됨 ({val[:16]}...)")
                elif isinstance(val, dict):
                    sid = val.get("session_id", "")
                    if sid:
                        state.session_id = sid
                        log(f"{name}: session_id 복원됨 ({sid[:16]}...)")
                    if val.get("was_busy"):
                        state.was_busy_before_restart = True
                        log(f"{name}: 재시작 전 busy 상태 복원됨")
                    if val.get("no_resume"):
                        state.no_resume_before_restart = True
                        log(f"{name}: no_resume 마킹 복원됨 (auto-resume 루프 방지)")
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
                "status": self._assess_health(state),
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
        """도구 호출 목록을 컴팩트한 한 줄로 포맷. 4개 초과 시 축약."""
        names = [t.replace("\U0001f527 ", "") for t in tool_lines]
        if len(names) <= 4:
            return "\u2500 \U0001f527 " + " \u2192 ".join(names)
        # 4개 초과: 처음 2개 + 마지막 1개 + 생략 표시
        shown = names[:2] + [f"...+{len(names) - 3}"] + names[-1:]
        return "\u2500 \U0001f527 " + " \u2192 ".join(shown)

    @staticmethod
    def _stabilize_markdown(text: str) -> str:
        """edit 전 미닫힌 코드블록을 임시로 닫아 마크다운 깨짐 방지."""
        if text.count("```") % 2 == 1:
            text += "\n```"
        return text

    def _should_auto_resume(self, state: SessionState) -> bool:
        """자동 재개 여부를 판단."""
        # no_resume 마킹 (슈퍼바이저/flag 재시작 시 busy였던 세션 → 루프 방지)
        if state.no_resume_before_restart:
            log(f"{state.name}: no_resume 마킹 → 자동 재개 스킵 (루프 방지)")
            state.no_resume_before_restart = False
            return False
        # reset 모드면 재개 안 함
        if state.last_restart_mode == "reset":
            log(f"{state.name}: reset 모드 → 자동 재개 스킵")
            return False
        # session_id 없으면 맥락 유실 → 재개 불가
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
        # auto-resume은 세션 개별 재시작(_restart_session)에서만 처리
        # 슈퍼바이저 초기 시작 시에는 대기 모드
        log(f"{state.name}: 세션 루프 시작 — 대기 모드")
        _idle_count = 0

        while not self._shutdown:
            try:
                msg_data = await asyncio.wait_for(
                    state.message_queue.get(), timeout=60
                )
                _idle_count = 0
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _idle_count += 1
                if _idle_count % 5 == 0:  # 5분마다 heartbeat
                    qsize = state.message_queue.qsize()
                    log(f"{state.name}: 세션 루프 대기 중 ({_idle_count}분, 큐={qsize}, connected={state.connected})")
                continue
            except BaseException:
                continue

            if not state.client:
                retry = msg_data.get("retry_noclient", 0)
                if retry < 10:
                    msg_data["retry_noclient"] = retry + 1
                    await state.message_queue.put(msg_data)
                    if retry % 3 == 0:  # 매 3회마다 로그 (스팸 방지)
                        log(f"{state.name}: client 없음, 재큐잉 ({retry+1}/10, 2초 대기)")
                    await asyncio.sleep(2)
                else:
                    log(f"{state.name}: client 없음, 재시도 소진 (10회/20초) → 메시지 드롭")
                    send_telegram(
                        f"❌ 세션 초기화 실패, 메시지 처리 불가\n원본: {msg_data['text'][:200]}",
                        state.config["bot_token"], state.name,
                    )
                continue

            if not state.connected:
                await self._restart_session(state, "세션 미연결")
                if not state.connected or not state.client:
                    retry = msg_data.get("retry_conn", 0)
                    if retry < 1:
                        msg_data["retry_conn"] = retry + 1
                        await state.message_queue.put(msg_data)
                        log(f"{state.name}: 세션 미연결, 재시도 큐잉 ({retry+1}/1)")
                        await asyncio.sleep(2)
                    else:
                        send_telegram(
                            f"❌ 세션 연결 실패, 메시지 처리 불가\n원본: {msg_data['text'][:200]}",
                            state.config["bot_token"], state.name,
                        )
                    continue

            was_queued = msg_data.get("retry_count", 0) > 0 or msg_data.get("queued_while_busy", False)
            state.busy = True
            state.busy_since = time.time()
            text = msg_data["text"]
            is_auto_resume = msg_data.get("auto_resume", False)
            msg_id = msg_data.get("msg_id", 0)

            # 사용자 메시지 → resume_count 리셋
            if not is_auto_resume and state.resume_count > 0:
                state.resume_count = 0

            # 대기 중이던 메시지 처리 시 구분선 전송 (이전 응답과 혼동 방지)
            if was_queued and not is_auto_resume:
                await async_send_telegram(
                    self._ahttp,
                    f"── 대기 메시지 처리 ──\n💬 {text[:100]}",
                    state.config["bot_token"], state.name,
                )

            log(f"{state.name}: 메시지 처리 시작: {text[:50]}")
            # 처리 시작 알림은 수신 확인(✔️)으로 대체됨

            try:
                client = state.client
                if not client:
                    continue
                # 버퍼 드레인: query() 전에 이전 턴의 잔여 메시지 제거 (N턴 밀림 방지)
                drain_count = 0
                drain_types = []
                try:
                    import anyio
                    if hasattr(client, '_query') and client._query:
                        stream = client._query._message_receive
                        while True:
                            try:
                                stale = stream.receive_nowait()
                                drain_count += 1
                                msg_type = stale.get("type", "?")
                                # 주요 내용 요약 (텍스트 블록이면 앞 50자)
                                preview = ""
                                if msg_type == "assistant":
                                    content = stale.get("message", {}).get("content", [])
                                    for b in content if isinstance(content, list) else []:
                                        if isinstance(b, dict) and b.get("type") == "text":
                                            preview = b.get("text", "")[:50]
                                            break
                                        elif isinstance(b, dict) and b.get("type") == "tool_use":
                                            preview = f"tool:{b.get('name', '?')}"
                                            break
                                elif msg_type == "result":
                                    preview = f"session={stale.get('session_id', '?')[:16]}"
                                drain_types.append(f"{msg_type}({preview})" if preview else msg_type)
                            except anyio.WouldBlock:
                                break
                            except anyio.ClosedResourceError:
                                break
                except Exception as e:
                    log(f"{state.name}: 버퍼 드레인 에러: {e}")
                if drain_count:
                    log(f"{state.name}: 버퍼 드레인 {drain_count}건 제거: {drain_types[:10]}")

                try:
                    await asyncio.wait_for(client.query(text), timeout=10)
                except asyncio.TimeoutError:
                    retry = msg_data.get("retry_timeout", 0)
                    log(f"{state.name}: query() 초기화 타임아웃 (10초), retry={retry}")
                    await self._restart_session(state, "query 초기화 타임아웃", mode="resume", force=True)
                    if retry < 2:
                        msg_data["retry_timeout"] = retry + 1
                        await state.message_queue.put(msg_data)
                        log(f"{state.name}: 타임아웃 재시도 큐잉 ({retry+1}/2)")
                        await asyncio.sleep((retry + 1) * 2)
                    else:
                        send_telegram(
                            f"❌ 응답 타임아웃 (재시도 소진)\n원본: {msg_data['text'][:200]}",
                            state.config["bot_token"], state.name,
                        )
                    state.busy = False
                    continue

                live_msg_id = 0  # 현재 editMessage 대상
                live_lines = []  # 현재 메시지에 쌓인 텍스트
                tool_lines = []  # 도구 호출 임시 버퍼 (텍스트 오면 정리)
                last_tool_name = ""  # 마지막 도구명 (ToolResult 판별용)
                msg_count = 0
                last_edit = 0.0
                edit_interval = 1.0  # 적응형 edit 간격 (초)
                query_start = time.time()  # 빠른 응답 감지용
                consecutive_edit_fails = 0  # 연속 edit 실패 횟수
                last_progress_notify = 0  # 마지막 중간 알림 시각
                bot_token = state.config["bot_token"]

                async for msg in client.receive_messages():
                    if msg is None:
                        continue
                    # client가 교체되었으면 (재시작) 현재 루프 중단
                    if state.client is not client:
                        log(f"{state.name}: client 교체 감지 → receive_messages 중단")
                        break
                    # 메시지 수신 타임아웃 체크 (10분 무응답 → 강제 중단)
                    if time.time() - state.busy_since > 600 and msg_count == 0:
                        log(f"{state.name}: 10분간 메시지 없음 → 강제 중단")
                        break
                    # 느린 응답 중간 알림 (2분마다)
                    elapsed = time.time() - state.busy_since
                    if elapsed > 120 and time.time() - last_progress_notify > 120:
                        mins = int(elapsed / 60)
                        await async_send_telegram(
                            self._ahttp,
                            f"⏳ 아직 처리 중... ({mins}분 경과, 도구 {msg_count}회 호출)",
                            bot_token, state.name,
                        )
                        last_progress_notify = time.time()
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
                            if need_new_msg and len(live_lines) > 1:
                                # 기존 메시지 마무리 후 새 메시지 시작 (2줄 이상일 때만)
                                prev = "\n".join(live_lines[:-1])
                                await async_edit_telegram(self._ahttp, prev, live_msg_id, bot_token, state.name)
                                new_start = live_lines[-1]
                                live_msg_id = await async_send_telegram(self._ahttp, new_start, bot_token, state.name)
                                live_lines = [new_start]
                                tool_lines = []
                                last_edit = now
                            elif not live_msg_id:
                                # 첫 메시지: 3초 버퍼링 — 빠른 응답은 edit 없이 최종 send로
                                elapsed_since_start = now - query_start
                                if elapsed_since_start >= 3.0:
                                    live_msg_id = await async_send_telegram(self._ahttp, content, bot_token, state.name)
                                    last_edit = now
                                # 3초 미만이면 전송 보류 (최종 전송에서 한 번에)
                            elif now - last_edit >= edit_interval:
                                # 4096자 한도 대비 여유 (prefix + 마진)
                                max_len = 4096 - len(f"[{state.name}] ") - 50
                                stable_content = _md_to_telegram_html(content)
                                if len(content) > max_len:
                                    prev = "\n".join(live_lines[:-1]) if len(live_lines) > 1 else "\n".join(live_lines)
                                    await async_edit_telegram(self._ahttp, _md_to_telegram_html(prev), live_msg_id, bot_token, state.name, use_html=True)
                                    new_start = live_lines[-1] if live_lines else ""
                                    live_msg_id = await async_send_telegram(self._ahttp, new_start, bot_token, state.name)
                                    live_lines = [new_start] if new_start else []
                                    tool_lines = []
                                else:
                                    ok = await async_edit_telegram(self._ahttp, stable_content, live_msg_id, bot_token, state.name, use_html=True)
                                    if not ok:
                                        consecutive_edit_fails += 1
                                        if consecutive_edit_fails >= 3:
                                            # rate limit 대응: 간격 증가
                                            edit_interval = min(edit_interval * 2, 5.0)
                                            consecutive_edit_fails = 0
                                        live_msg_id = await async_send_telegram(self._ahttp, stable_content, bot_token, state.name, use_html=True)
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
                            elif last_tool_name in ("Edit", "Write", "NotebookEdit", "Read", "Grep", "Glob"):
                                # 코드/파일 관련 결과는 길이만 표시 (내용 생략)
                                if tool_lines:
                                    tool_lines[-1] += f" ({len(result_text)}자)"
                                log(f"{state.name}: [result] {last_tool_name} ({len(result_text)}자, 생략)")
                            elif len(result_text) <= 500:
                                if tool_lines:
                                    live_lines.append(self._format_tool_line(tool_lines))
                                    tool_lines = []
                                live_lines.append(result_text)
                                log(f"{state.name}: [result] short ({len(result_text)}자)")
                            else:
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
                                live_msg_id = await async_send_telegram(self._ahttp, _md_to_telegram_html(content), bot_token, state.name, use_html=True)
                                last_edit = now
                            elif now - last_edit >= edit_interval:
                                stable_content = _md_to_telegram_html(content)
                                ok = await async_edit_telegram(self._ahttp, stable_content, live_msg_id, bot_token, state.name, use_html=True)
                                if not ok:
                                    consecutive_edit_fails += 1
                                    if consecutive_edit_fails >= 3:
                                        edit_interval = min(edit_interval * 2, 5.0)
                                        consecutive_edit_fails = 0
                                    live_msg_id = await async_send_telegram(self._ahttp, stable_content, bot_token, state.name, use_html=True)
                                else:
                                    consecutive_edit_fails = 0
                                    if edit_interval > 1.0:
                                        edit_interval = max(edit_interval - 0.5, 1.0)
                                last_edit = now

                    elif isinstance(msg, ResultMessage):
                        if hasattr(msg, "session_id") and msg.session_id:
                            state.session_id = msg.session_id
                            self._save_session_ids()
                        if msg.usage:
                            log(f"{state.name}: [usage] {msg.usage}")
                        break

                # 최종 업데이트 (HTML 변환 적용)
                if tool_lines:
                    live_lines.append(self._format_tool_line(tool_lines))
                if live_lines:
                    content = "\n".join(live_lines)
                    # plain text에서 분할 후 각 청크별 HTML 변환 (태그 절단 방지)
                    chunks = [_md_to_telegram_html(c) for c in _split_message(content)]
                    elapsed = time.time() - query_start
                    # 빠른 응답(3초 이내): editMessage 대신 새 메시지로 전송
                    # → editMessage 지연으로 인한 "답변 밀림" 방지
                    if live_msg_id and elapsed >= 3.0:
                        ok = await async_edit_telegram(self._ahttp, chunks[0], live_msg_id, bot_token, state.name, use_html=True)
                        if not ok:
                            await async_edit_telegram(self._ahttp, _split_message(content)[0], live_msg_id, bot_token, state.name)
                        for chunk in chunks[1:]:
                            await async_send_telegram(self._ahttp, chunk, bot_token, state.name, use_html=True)
                    else:
                        # 빠른 응답이거나 live_msg_id 없음: 새 메시지로 전송
                        if live_msg_id:
                            # 기존 live 메시지 삭제 (중복 방지)
                            try:
                                await self._ahttp.post(
                                    f"https://api.telegram.org/bot{bot_token}/deleteMessage",
                                    json={"chat_id": CHAT_ID, "message_id": live_msg_id},
                                    timeout=5,
                                )
                            except Exception:
                                pass
                        for chunk in chunks:
                            await async_send_telegram(self._ahttp, chunk, bot_token, state.name, use_html=True)
                    log(f"{state.name}: 최종 전송 ({len(content)}자, {len(chunks)}청크, {elapsed:.1f}s)")
                else:
                    log(f"{state.name}: 빈 응답")
                    await async_send_telegram(self._ahttp, "⚠️ 빈 응답", bot_token, state.name)

                log(f"{state.name}: 처리 완료")

                # 처리 완료 알림 (새 메시지, 알림 옴)
                asyncio.create_task(async_send_telegram(self._ahttp, "✅", bot_token, state.name))

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

                # 자동 리셋 제거 — Claude auto-compact가 컨텍스트 관리
                # 필요 시 수동으로 /reset 사용

            except BaseException as e:
                # CancelledError 포함 — 루프가 죽지 않도록 모든 예외 포착
                err_name = type(e).__name__
                err_str = str(e)
                log(f"{state.name}: 처리 에러 ({err_name}): {e}")
                state.error_count += 1

                # 이미지 누적 에러 → 자동 reset (resume으로는 해결 불가)
                if "dimension limit" in err_str or "many-image" in err_str:
                    log(f"{state.name}: 이미지 누적 에러 감지 → reset 모드 재시작")
                    send_telegram(
                        f"⚠️ 이미지 누적으로 컨텍스트 초과\n자동 reset 진행",
                        state.config["bot_token"], state.name,
                    )
                    await self._restart_session(state, "이미지 누적 에러", mode="reset", force=True)
                    continue

                if state.restarting:
                    # 리셋/재시작으로 인한 프로세스 종료 — 의도된 에러이므로 재시도 불필요
                    log(f"{state.name}: 재시작 중 에러 무시 ({err_name})")
                elif isinstance(e, (asyncio.CancelledError, KeyboardInterrupt)):
                    # cancel/interrupt는 재시도 없이 다음 메시지로
                    log(f"{state.name}: {err_name} — 루프 유지, 다음 메시지 대기")
                else:
                    retry = msg_data.get("retry_error", 0)
                    if retry < 1:
                        msg_data["retry_error"] = retry + 1
                        await state.message_queue.put(msg_data)
                        log(f"{state.name}: 에러 재시도 큐잉 ({retry+1}/1)")
                        await asyncio.sleep(2)
                    else:
                        send_telegram(
                            f"❌ 처리 실패: {e}\n원본: {msg_data['text'][:200]}",
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

        # offset 복원 (저장된 offset이 있으면 사용, 없으면 flush)
        saved_offset = self._load_offset(bot_id)
        if saved_offset is not None:
            self._update_ids[bot_id] = saved_offset
            log(f"{name}: offset 복원 = {saved_offset}")
        else:
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
        _poll_count = 0
        while not self._shutdown:
            _poll_count += 1
            if _poll_count % 20 == 0:  # ~10분마다 (25초 long poll × 20)
                log(f"{name}: 폴링 루프 정상 (cycle={_poll_count}, errors={error_count})")
            last_id = self._update_ids.get(bot_id, 0)
            try:
                r = await self._ahttp.get(
                    f"https://api.telegram.org/bot{bot_token}/getUpdates",
                    params={
                        "offset": last_id + 1,
                        "timeout": 25,
                        "allowed_updates": ["message", "edited_message"],
                    },
                    timeout=35,
                )
                r.raise_for_status()
                updates = r.json().get("result", [])
                for u in updates:
                    update_id = u["update_id"]
                    msg = u.get("message") or u.get("edited_message") or {}
                    is_edited = "edited_message" in u
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

                    # 문서/파일 메시지 처리
                    if not text and msg.get("document"):
                        doc = msg["document"]
                        file_name = doc.get("file_name", "unknown")
                        file_id = doc.get("file_id", "")
                        caption = msg.get("caption", "")
                        if file_id:
                            try:
                                fr = await self._ahttp.get(
                                    f"https://api.telegram.org/bot{bot_token}/getFile",
                                    params={"file_id": file_id}, timeout=10,
                                )
                                file_path = fr.json().get("result", {}).get("file_path", "")
                                if file_path:
                                    dl_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
                                    save_dir = os.path.join(LOGS_DIR, "files")
                                    os.makedirs(save_dir, exist_ok=True)
                                    save_path = os.path.join(save_dir, file_name)
                                    dr = await self._ahttp.get(dl_url, timeout=30)
                                    with open(save_path, "wb") as f:
                                        f.write(dr.content)
                                    log(f"{name}: 파일 다운로드 완료: {save_path}")
                                    text = f"이 파일을 확인해줘: {save_path}"
                                    if caption:
                                        text = f"{caption}\n\n파일: {save_path}"
                            except Exception as e:
                                log(f"{name}: 파일 다운로드 실패: {e}")

                    if not text:
                        self._update_ids[bot_id] = update_id
                        continue

                    if self._handle_command(text, bot_token):
                        log(f"{name}: 명령어 처리: {text}")
                        self._update_ids[bot_id] = update_id
                        continue

                    sender = msg.get("from", {}).get("first_name", "")
                    edit_tag = " [수정]" if is_edited else ""
                    full_text = f"{sender}{edit_tag}: {text}"

                    # 중복 메시지 제거 (message_id 기반)
                    msg_key = f"{name}_{msg_id}"
                    if msg_key in self._last_msg_map:
                        self._update_ids[bot_id] = update_id
                        continue
                    # 네트워크 재전송 중복 제거 (같은 date + 같은 텍스트)
                    msg_date_key = f"{name}_d{msg_date}_{text}"
                    if msg_date_key in self._last_msg_map:
                        log(f"{name}: 동일 date+텍스트 중복 스킵 (date={msg_date}): {text[:30]}")
                        self._update_ids[bot_id] = update_id
                        continue
                    self._last_msg_map[msg_key] = time.time()
                    self._last_msg_map[msg_date_key] = time.time()
                    # 오래된 항목 정리 (100개 초과 시)
                    if len(self._last_msg_map) > 100:
                        cutoff = time.time() - 300
                        self._last_msg_map = {k: v for k, v in self._last_msg_map.items() if v > cutoff}

                    # pause 상태: restart/reset 명령은 통과, 나머지 거부
                    pause_flag = Path(TELEGRAM_DIR) / f"pause_{name}.flag"
                    if pause_flag.exists():
                        text_lower = text.strip().lower()
                        if text_lower in ("restart", "reset", "재시작", "리셋", "/restart", "/reset"):
                            # pause 해제 + restart flag 생성
                            pause_flag.unlink(missing_ok=True)
                            mode = "reset" if "reset" in text_lower or "리셋" in text_lower else "resume"
                            restart_flag = Path(TELEGRAM_DIR) / f"restart_request_{name}.flag"
                            restart_flag.write_text(f"force,{mode}" if mode != "resume" else "force")
                            await async_send_telegram(self._ahttp, f"▶️ {name} pause 해제 + 재시작 요청됨", bot_token, name, reply_to=msg_id)
                            self._update_ids[bot_id] = update_id
                            self._save_offset(bot_id, update_id)
                            log(f"{name}: PAUSED → 해제 (텔레그램 명령: {text_lower})")
                            continue
                        await async_send_telegram(self._ahttp, f"⏸️ {name} 일시정지 중. restart 또는 reset을 입력하세요.", bot_token, name, reply_to=msg_id)
                        self._update_ids[bot_id] = update_id
                        self._save_offset(bot_id, update_id)
                        log(f"{name}: PAUSED — 메시지 거부: {text[:50]}")
                        continue

                    # 수신 확인 (큐 투입 전에 보내서 응답보다 먼저 도착 보장)
                    if state.busy:
                        qsize = state.message_queue.qsize() + 1
                        ack = f"✔️ (처리 중, 대기 {qsize}건)"
                    else:
                        ack = "✔️"
                    await async_send_telegram(self._ahttp, ack, bot_token, name, reply_to=msg_id)

                    await state.message_queue.put({
                        "text": full_text,
                        "msg_id": msg_id,
                        "update_id": update_id,
                        "retry_count": 0,
                        "queued_while_busy": state.busy,
                    })
                    # 큐에 넣은 즉시 offset 갱신 (재폴링 방지) + 파일 저장
                    self._update_ids[bot_id] = update_id
                    self._save_offset(bot_id, update_id)
                    log(f"{name}: 메시지 수신: {text[:50]}")
                if error_count > 0:
                    error_count = 0
            except Exception as e:
                error_count += 1
                if error_count % 10 == 1:
                    import traceback
                    tb = traceback.format_exc()
                    log(f"{name}: 폴링 에러 #{error_count}: {repr(e)}\n{tb}")
                await asyncio.sleep(min(2 ** min(error_count, 5), 30))

    async def shutdown(self):
        self._shutdown = True
        _notify_all("[HUB] 슈퍼바이저 종료 중...")
        if self._ahttp:
            await self._ahttp.aclose()
        # ask 클라이언트 정리
        if self._ask_client:
            await self._safe_disconnect(self._ask_client, "ask")
            self._ask_client = None
        # 세션 클라이언트 disconnect
        for name, state in self.sessions.items():
            if state.client:
                await self._safe_disconnect(state.client, name)
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

"""
TeleClaw — Claude Code SDK 기반 텔레그램 봇
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

# Windows cp949 인코딩 문제 방지 — stdout/stderr를 UTF-8로 강제
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from claude_agent_sdk import (
    ClaudeSDKClient, ClaudeAgentOptions,
    AssistantMessage, UserMessage, ResultMessage,
    HookMatcher,
)

from .config import (
    PROJECTS, CHAT_ID, ALLOWED_USERS, TELECLAW_DIR, LOGS_DIR, LOG_FILE,
    STATUS_FILE, SESSION_IDS_FILE, DATA_DIR,
    HEALTH_CHECK_INTERVAL, STUCK_THRESHOLD,
    MAX_RESTARTS_PER_WINDOW, RESTART_WINDOW,
    AUTO_RESUME_ENABLED, AUTO_RESUME_MODE, AUTO_RESUME_PROMPTS,
    ICON_THINKING, ICON_DONE, OUTPUT_LEVEL,
)
from .logging_utils import log, _find_existing_teleclaw, _write_lock, _release_lock
from .channel_telegram import TelegramChannel
from .session import SessionState
from .commands import handle_command, _get_usage
from .messages import msg
from . import state_db as db
from .file_handler import download_photo, download_photo_via_channel, download_doc_via_channel
from .stream_handler import (
    StreamContext, tool_summary, format_tool_line, stabilize_markdown,
    process_stream_message, finalize_response,
)


# --- SDK 스트림 전수 로깅 ---

class _StreamDumper:
    """SDK 메시지를 JSON Lines 파일에 덤프. 디버깅/테스트용."""

    def __init__(self, session_name: str):
        ts = time.strftime("%Y%m%d_%H%M%S")
        os.makedirs(LOGS_DIR, exist_ok=True)
        self._path = os.path.join(LOGS_DIR, f"stream_dump_{session_name}_{ts}.jsonl")
        self._f = open(self._path, "a", encoding="utf-8")
        log(f"{session_name}: stream dump → {self._path}")

    def dump(self, sdk_msg):
        """SDK 메시지 1건을 JSON Lines로 기록."""
        try:
            record = {
                "timestamp": time.time(),
                "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "type": type(sdk_msg).__name__,
                "raw": self._serialize(sdk_msg),
            }
            # block 상세 정보 추출
            blocks = []
            for block in getattr(sdk_msg, "content", []) or []:
                b = {"block_type": type(block).__name__}
                if hasattr(block, "text"):
                    b["text"] = block.text[:2000] if block.text else ""
                if hasattr(block, "name"):
                    b["name"] = block.name
                if hasattr(block, "input"):
                    b["input"] = self._safe_json(block.input)
                if hasattr(block, "content"):
                    b["content"] = self._safe_json(block.content)
                if hasattr(block, "thinking"):
                    b["thinking"] = (block.thinking or "")[:500]
                if hasattr(block, "tool_use_id"):
                    b["tool_use_id"] = block.tool_use_id
                blocks.append(b)
            if blocks:
                record["blocks"] = blocks
            self._f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._f.flush()
        except Exception as e:
            log(f"stream_dump error: {e}")

    def _serialize(self, obj) -> dict:
        """객체를 dict로 직렬화. 직렬화 불가 필드는 str() 변환."""
        try:
            d = vars(obj) if hasattr(obj, "__dict__") else {"value": str(obj)}
        except Exception:
            return {"value": str(obj)}
        result = {}
        for k, v in d.items():
            result[k] = self._safe_json(v)
        return result

    @staticmethod
    def _safe_json(v):
        """JSON 직렬화 가능하면 그대로, 아니면 str() 변환."""
        try:
            json.dumps(v, ensure_ascii=False)
            return v
        except (TypeError, ValueError):
            return str(v)

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass


class TeleClaw:
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
        self._fresh_start = True  # TeleClaw 프로세스 시작 직후 (개별 세션 재시작과 구분)
        self.output_level = OUTPUT_LEVEL  # minimal / normal (런타임 /mode로 전환 가능)

    async def start(self):
        log("TeleClaw 시작")
        db.init()
        # 세션 초기화
        for name, config in PROJECTS.items():
            state = SessionState(name=name, config=config)
            channel = TelegramChannel(
                bot_token=config["bot_token"],
                chat_id=CHAT_ID,
                bot_name=name,
            )
            state.channel = channel
            self.sessions[name] = state

        self._load_session_ids()

        # AsyncClient 먼저 생성 (폴링에 필요)
        self._ahttp = httpx.AsyncClient(timeout=35)

        # 각 채널에 ahttp 설정
        for state in self.sessions.values():
            state.channel.set_ahttp(self._ahttp)

        # 시작 알림 (채널 초기화 후)
        self._broadcast_sync(msg("sv_start"))

        # 폴링 + 유틸리티 루프 즉시 시작 (연결 전에도 메시지 수신 가능)
        tasks = []
        for name, state in self.sessions.items():
            tasks.append(asyncio.create_task(self._bot_poll_loop(state)))
        tasks.append(asyncio.create_task(self._restart_flag_loop()))
        tasks.append(asyncio.create_task(self._health_check_loop()))
        tasks.append(asyncio.create_task(self._watchdog_loop()))

        # 세션 병렬 연결 (다운타임 최소화, pause 세션 제외)
        async def _connect_and_init(state):
            if db.is_paused(state.name):
                log(f"{state.name}: PAUSED — 연결 스킵")
                return
            await self._connect_session(state)
            if state.connected:
                await self._wait_mcp_ready(state, timeout=5)
                state.channel.send_sync(msg("sv_ready"), notify=True)
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
        await self._broadcast(msg("sv_init_done", elapsed=elapsed, names=', '.join(connected)))
        log("모든 루프 시작됨")

        # TeleClaw 시작 시에는 자동 재개 안 함
        # (세션이 아직 불안정할 수 있고, was_busy_before_restart도 없음)
        self._fresh_start = False
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                log(f"task[{i}] 에러로 종료: {r}")
                await self._broadcast(msg("sv_task_error", i=i, error=r))


    async def _safe_disconnect(self, client, name: str):
        """공식 disconnect() API로 세션 종료."""
        try:
            await client.disconnect()
            log(f"{name}: disconnect 완료")
        except Exception as e:
            log(f"{name}: disconnect 실패 ({e}), 프로세스 직접 종료 시도")
            try:
                transport = getattr(client, "_transport", None)
                proc = getattr(transport, "_process", None) if transport else None
                if proc and proc.returncode is None:
                    proc.terminate()
                    log(f"{name}: 프로세스 terminate (pid={proc.pid})")
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

            # 훅 콜백 정의
            _ch = state.channel
            _name = state.name

            async def _on_tool_failure(input, matcher, ctx, ch=_ch, name=_name):
                try:
                    tool = input.tool_name
                    err = input.error[:200] if input.error else "?"
                    log(f"{name}: [hook] PostToolUseFailure: {tool} — {err}")
                    await ch.send(msg("hook_tool_failure", name=name, tool=tool, err=err))
                except Exception as e:
                    log(f"{name}: [hook] 콜백 에러: {e}")
                return {}

            async def _on_notification(input, matcher, ctx, ch=_ch, name=_name):
                try:
                    log(f"{name}: [hook] Notification: {input.notification_type} — {input.message[:100]}")
                    await ch.send(msg("notification", name=name, message=input.message[:500]))
                except Exception as e:
                    log(f"{name}: [hook] 콜백 에러: {e}")
                return {}

            options = ClaudeAgentOptions(
                permission_mode="bypassPermissions",
                cwd=state.config["cwd"],
                mcp_servers=mcp_servers,
                max_turns=50,
                stderr=lambda line, _name=state.name: log(f"{_name}: [stderr] {line.rstrip()}"),
                hooks={
                    "PostToolUseFailure": [HookMatcher(hooks=[_on_tool_failure])],
                    "Notification": [HookMatcher(hooks=[_on_notification])],
                },
            )

            # reset 모드: 컨텍스트 초기화 (새 대화)
            if mode == "reset":
                state.session_id = None
                log(f"{state.name}: reset 모드 (새 대화)")
            else:
                # resume/new 모두 기존 컨텍스트 유지
                if state.session_id is not None:
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
            state.channel.send_sync(msg("sv_connected", name=state.name), notify=True)
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
            options = ClaudeAgentOptions(
                permission_mode="bypassPermissions",
                cwd=TELECLAW_DIR,
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

    def _broadcast_sync(self, text: str):
        """전체 세션에 동기 알림."""
        sent = set()
        for state in self.sessions.values():
            token = state.config.get("bot_token", "")
            if token and token not in sent:
                state.channel.send_sync(text)
                sent.add(token)

    async def _broadcast(self, text: str):
        """전체 세션에 비동기 알림."""
        sent = set()
        for state in self.sessions.values():
            token = state.config.get("bot_token", "")
            if token and token not in sent:
                await state.channel.send(text)
                sent.add(token)

    def _channel_by_token(self, bot_token: str):
        """bot_token에 해당하는 channel 반환."""
        for state in self.sessions.values():
            if state.config["bot_token"] == bot_token:
                return state.channel
        return None

    async def _handle_ask(self, question: str, bot_token: str):
        """ask 명령 비동기 처리."""
        ch = self._channel_by_token(bot_token)
        if self._ask_busy:
            ch.send_sync(msg("ask_busy"))
            return
        self._ask_busy = True
        try:
            if not await self._ensure_ask_client():
                ch.send_sync(msg("ask_connect_fail"))
                return
            ch.send_sync(msg("ask_processing"))
            await self._ask_client.query(question)
            answer_parts = []
            async for ask_msg in self._ask_client.receive_messages():
                if ask_msg is None:
                    continue
                if isinstance(ask_msg, AssistantMessage):
                    for block in ask_msg.content:
                        if hasattr(block, "text") and block.text.strip():
                            answer_parts.append(block.text.strip())
                elif isinstance(ask_msg, ResultMessage):
                    break
            answer = "\n".join(answer_parts) if answer_parts else "(빈 응답)"
            if len(answer) > 3900:
                answer = answer[:3900] + "\n... (잘림)"
            ch.send_sync(msg("ask_response", answer=answer))
        except Exception as e:
            log(f"ask 처리 실패: {e}")
            ch.send_sync(msg("ask_error", error=str(e)))
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
                limit_msg = msg("restart_limit", name=state.name, max=MAX_RESTARTS_PER_WINDOW, window=RESTART_WINDOW//60, reason=reason, remaining=wait_remaining)
                log(limit_msg)
                if now - state.last_notify_time > 300:
                    self._broadcast_sync(limit_msg)
                    state.last_notify_time = now
                return

        state.restarting = True
        try:
            log(f"{state.name}: 재시작 시도 (사유: {reason})")
            state.channel.send_sync(msg("restart_reason", name=state.name, reason=reason))

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
                state.channel.send_sync(msg("restart_done", name=state.name), notify=True)

                # auto-resume: 세션 개별 재시작 시에만
                # reset(new) 또는 TeleClaw 초기 시작 시에는 스킵 (start()에서 check 모드로 처리)
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

                # teleclaw 자체 재시작 체크 (DB)
                sv_cmd = db.pop_command("teleclaw")
                if sv_cmd:
                    mode = "resume"
                    force = False
                    args = sv_cmd.get("args", "")
                    for t in [x.strip() for x in args.split(",") if x.strip()]:
                        if t == "force": force = True
                        elif t in ("resume", "reset"): mode = t
                    cooldown = 300  # 5분
                    elapsed = time.time() - self._start_time
                    if not force and elapsed < cooldown:
                        log(f"teleclaw 자체 재시작 flag 무시 (쿨다운: {int(cooldown - elapsed)}초 남음)")
                    else:
                        # busy 세션은 no_resume 마킹 (auto-resume 루프 방지)
                        self._save_session_ids(no_resume_if_busy=True)
                        # busy 세션이 있으면 완료 대기 (최대 60초)
                        busy_sessions = [n for n, s in self.sessions.items() if s.busy]
                        if busy_sessions and not force:
                            log(f"teleclaw 자체 재시작 flag 감지 — busy 세션 대기: {', '.join(busy_sessions)}")
                            waited = 0
                            while waited < 60:
                                await asyncio.sleep(2)
                                waited += 2
                                busy_sessions = [n for n, s in self.sessions.items() if s.busy]
                                if not busy_sessions:
                                    break
                            if busy_sessions:
                                log(f"graceful 대기 60초 초과, 강제 종료 (busy: {', '.join(busy_sessions)})")
                        log(f"teleclaw 자체 재시작 flag 감지 (mode={mode}, force={force}) → 프로세스 종료")
                        await self._broadcast(msg("sv_self_restart", mode=mode))
                        self._shutdown = True
                        os._exit(0)  # wrapper가 자동 재시작

                for name, state in self.sessions.items():
                    cmd = db.pop_command(name)
                    if not cmd:
                        continue
                    mode = "resume"
                    force = False
                    no_resume = False
                    command = cmd.get("command", "")
                    if command == "pause":
                        db.set_paused(name, True)
                        log(f"{name}: pause 명령 (DB)")
                        continue
                    if command == "wakeup":
                        db.set_paused(name, False)
                        log(f"{name}: wakeup 명령 (DB)")
                        continue
                    args = cmd.get("args", "")
                    tokens = [t.strip() for t in args.split(",") if t.strip()]
                    for t in tokens:
                        if t == "force": force = True
                        elif t == "noresume": no_resume = True
                        elif t in ("new", "resume", "reset"): mode = t
                    log(f"{name}: {command} 명령 (DB, mode={mode})")
                    # restart 요청 시 pause 자동 해제
                    db.set_paused(name, False)
                    state.no_resume_before_restart = False
                    log(f"{name}: restart 실행 (mode={mode}, force={force}, noresume={no_resume})")
                    await self._restart_session(state, f"명령 요청 (mode={mode})", mode=mode, force=force, no_resume=no_resume)
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
                    if db.is_paused(name):
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
        no_resume_if_busy=True: TeleClaw 자체 재시작 시, busy 세션은 no_resume 마킹."""
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
        """TeleClaw 명령어 처리. 처리했으면 True 반환."""
        ch = self._channel_by_token(bot_token)
        return handle_command(self, text, bot_token, ch)

    def _find_session_by_token(self, bot_token: str) -> str | None:
        for name, state in self.sessions.items():
            if state.config["bot_token"] == bot_token:
                return name
        return None

    def _get_usage(self) -> str:
        return _get_usage(self._http)

    # static 메서드는 stream_handler 모듈로 이동:
    # tool_summary, format_tool_line, stabilize_markdown
    # 하위 호환 유지
    _tool_summary = staticmethod(tool_summary)
    _format_tool_line = staticmethod(format_tool_line)
    _stabilize_markdown = staticmethod(stabilize_markdown)

    def _should_auto_resume(self, state: SessionState) -> bool:
        """자동 재개 여부를 판단."""
        # no_resume 마킹 (TeleClaw/flag 재시작 시 busy였던 세션 → 루프 방지)
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
            state.channel.send_sync(msg("auto_resume_fail", name=state.name))
            state.resume_count = 0
            return False
        return True

    async def _session_loop(self, state: SessionState):
        # auto-resume은 세션 개별 재시작(_restart_session)에서만 처리
        # TeleClaw 초기 시작 시에는 대기 모드
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
                    state.channel.send_sync(msg("session_init_fail", text=msg_data['text'][:200]))
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
                        state.channel.send_sync(msg("session_connect_fail", text=msg_data['text'][:200]))
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
                await state.channel.send(msg("pending_message", text=text[:100]))

            log(f"{state.name}: 메시지 처리 시작: {text[:50]}")
            # 처리 시작 알림은 수신 확인(✔️)으로 대체됨

            try:
                client = state.client
                if not client:
                    continue
                ch = state.channel

                # 경량 드레인: 이전 턴 잔여 메시지 제거 (재시도 시 스킵)
                is_retry = msg_data.get("retry_empty", 0) > 0 or msg_data.get("retry_resume", 0) > 0
                if not is_retry:
                    try:
                        import anyio
                        if hasattr(client, '_query') and client._query:
                            stream = client._query._message_receive
                            drained = 0
                            while True:
                                try:
                                    stream.receive_nowait()
                                    drained += 1
                                except (anyio.WouldBlock, anyio.ClosedResourceError):
                                    break
                            if drained:
                                log(f"{state.name}: 경량 드레인 {drained}건 제거")
                    except Exception:
                        pass

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
                        state.channel.send_sync(msg("timeout_exhausted", text=msg_data['text'][:200]))
                    state.busy = False
                    continue

                ctx = StreamContext()
                stream_dumper = _StreamDumper(state.name)

                # raw 메시지 로깅 래퍼 — parse_message가 None 반환하는 케이스 감지
                from claude_agent_sdk._internal.message_parser import parse_message as _sdk_parse
                async def _logging_receive():
                    async for raw_data in client._query.receive_messages():
                        msg = _sdk_parse(raw_data)
                        if msg is None:
                            msg_type = raw_data.get("type", "?") if isinstance(raw_data, dict) else "?"
                            log(f"{state.name}: [sdk-skip] type={msg_type} keys={list(raw_data.keys()) if isinstance(raw_data, dict) else '?'}")
                        if msg is not None:
                            yield msg
                msg_iter = _logging_receive().__aiter__()
                while True:
                    # client 교체 감지 (재시작으로 인한 프로세스 종료)
                    if state.client is not client:
                        log(f"{state.name}: client 교체 감지 → receive_messages 중단")
                        break
                    try:
                        sdk_msg = await asyncio.wait_for(msg_iter.__anext__(), timeout=30)
                    except asyncio.TimeoutError:
                        if state.client is not client:
                            log(f"{state.name}: 수신 타임아웃 + client 교체 → 루프 중단")
                            break
                        continue
                    except StopAsyncIteration:
                        # init만 오고 실제 응답 없이 스트림 종료 → 재시도
                        if ctx.msg_count <= 1 and not ctx.live_lines:
                            retry = msg_data.get("retry_empty", 0)
                            if retry < 2:
                                msg_data["retry_empty"] = retry + 1
                                log(f"{state.name}: 빈 스트림 → 재시도 ({retry + 1}/2)")
                                await state.message_queue.put(msg_data)
                                state.busy = False
                                break
                            else:
                                # 2회 재시도 실패 → resume으로 세션 복구 후 재시도
                                if msg_data.get("retry_resume", 0) < 1:
                                    msg_data["retry_resume"] = 1
                                    msg_data["retry_empty"] = 0
                                    log(f"{state.name}: 빈 스트림 2회 실패 → resume 후 재시도")
                                    await self._restart_session(state, "빈 스트림 resume", mode="resume", force=True)
                                    await state.message_queue.put(msg_data)
                                    state.busy = False
                                    break
                        break
                    if sdk_msg is None:
                        continue
                    stream_dumper.dump(sdk_msg)
                    # 메시지 수신 타임아웃 체크 (10분 무응답 → 강제 중단)
                    if time.time() - state.busy_since > 600 and ctx.msg_count == 0:
                        log(f"{state.name}: 10분간 메시지 없음 → 강제 중단")
                        break
                    # 느린 응답 중간 알림 (2분마다)
                    elapsed = time.time() - state.busy_since
                    if elapsed > 120 and time.time() - ctx.last_progress_notify > 120:
                        mins = int(elapsed / 60)
                        await ch.send(msg("still_processing", mins=mins, tools=ctx.msg_count))
                        ctx.last_progress_notify = time.time()
                    ctx.msg_count += 1

                    done = await process_stream_message(
                        sdk_msg, state, ch, ctx,
                        output_level=self.output_level,
                        save_session_ids_fn=self._save_session_ids,
                    )
                    if done:
                        # ResultMessage 수신 → end까지 잔여 메시지 소비 (N턴 밀림 방지)
                        try:
                            async def _drain_end():
                                async for _ in msg_iter:
                                    pass
                            await asyncio.wait_for(_drain_end(), timeout=0.5)
                        except (asyncio.TimeoutError, Exception):
                            pass
                        break

                # 최종 전송
                await finalize_response(state, ch, ctx)

                log(f"{state.name}: 처리 완료")

                # 처리 완료 알림 (새 메시지, 알림 옴)
                # await로 순서 보장: MCP 결과(💬) → finalize → ✅ 순서
                await ch.send(ICON_DONE)

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
                    state.channel.send_sync(msg("image_overflow"))
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
                        state.channel.send_sync(msg("process_fail", error=e, text=msg_data['text'][:200]))
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
        ch = state.channel

        # offset 복원 (저장된 offset이 있으면 사용, 없으면 flush)
        saved_offset = self._load_offset(bot_id)
        if saved_offset is not None:
            self._update_ids[bot_id] = saved_offset
            ch.set_offset(saved_offset + 1)
            log(f"{name}: offset 복원 = {saved_offset}")
        else:
            # flush: 기존 메시지를 모두 소비하여 offset 초기화
            try:
                flush_msgs = await ch.poll(timeout=0)
                # poll 내부에서 offset이 자동 갱신됨
                last_offset = ch.get_offset() - 1 if ch.get_offset() > 0 else 0
                self._update_ids[bot_id] = last_offset
                log(f"{name}: offset 초기화 = {last_offset} (flushed {len(flush_msgs)})")
            except Exception as e:
                log(f"{name}: offset 초기화 실패: {e}")
                self._update_ids[bot_id] = 0

        error_count = 0
        _poll_count = 0
        while not self._shutdown:
            _poll_count += 1
            if _poll_count % 20 == 0:  # ~10분마다 (25초 long poll × 20)
                log(f"{name}: 폴링 루프 정상 (cycle={_poll_count}, errors={error_count})")
            try:
                messages = await ch.poll(timeout=25)
                for m in messages:
                    raw = m.get("_raw", {})
                    msg_id_str = m["id"]
                    msg_id = int(msg_id_str) if msg_id_str else 0
                    from_id = m.get("from_id", "")
                    if not ALLOWED_USERS or (from_id and str(from_id) not in ALLOWED_USERS):
                        log(f"{name}: 미허용 사용자 메시지 무시 (from_id={from_id})")
                        continue
                    msg_date = m.get("date", 0)
                    if msg_date < self._start_time:
                        log(f"{name}: 오래된 메시지 스킵 (date={msg_date})")
                        continue
                    text = m.get("text", "")
                    is_edited = raw.get("_is_edited", False) if raw else False
                    files = m.get("files", [])

                    # 이미지 메시지 처리
                    if not text and files:
                        for f_info in files:
                            if f_info.get("type") == "photo":
                                photo_path = await download_photo_via_channel(ch, f_info["file_id"], name)
                                if photo_path:
                                    caption = raw.get("caption", "") if raw else ""
                                    text = f"이 이미지를 확인해줘: {photo_path}"
                                    if caption:
                                        text = f"{caption}\n\n이미지: {photo_path}"
                                break
                            elif f_info.get("type") == "document":
                                file_id = f_info.get("file_id", "")
                                file_name = f_info.get("name", "unknown")
                                caption = raw.get("caption", "") if raw else ""
                                if file_id:
                                    doc_path = await download_doc_via_channel(ch, file_id, file_name, name)
                                    if doc_path:
                                        text = f"이 파일을 확인해줘: {doc_path}"
                                        if caption:
                                            text = f"{caption}\n\n파일: {doc_path}"
                                break

                    if not text:
                        continue

                    if await asyncio.to_thread(self._handle_command, text, bot_token):
                        log(f"{name}: 명령어 처리: {text}")
                        continue

                    sender = raw.get("from", {}).get("first_name", "") if raw else ""
                    edit_tag = " [수정]" if is_edited else ""
                    # /로 시작하는 슬래시 명령은 프리픽스 없이 전달 (Claude Code 내장 명령 호환)
                    if text.startswith("/"):
                        full_text = text
                    else:
                        full_text = f"{sender}{edit_tag}: {text}"

                    # 중복 메시지 제거 (message_id 기반)
                    msg_key = f"{name}_{msg_id}"
                    if msg_key in self._last_msg_map:
                        continue
                    # 네트워크 재전송 중복 제거 (같은 date + 같은 텍스트)
                    msg_date_key = f"{name}_d{msg_date}_{text}"
                    if msg_date_key in self._last_msg_map:
                        log(f"{name}: 동일 date+텍스트 중복 스킵 (date={msg_date}): {text[:30]}")
                        continue
                    self._last_msg_map[msg_key] = time.time()
                    self._last_msg_map[msg_date_key] = time.time()
                    # 오래된 항목 정리 (100개 초과 시)
                    if len(self._last_msg_map) > 100:
                        cutoff = time.time() - 300
                        self._last_msg_map = {k: v for k, v in self._last_msg_map.items() if v > cutoff}

                    # pause 상태: restart/reset 명령은 통과, 나머지 거부
                    if db.is_paused(name):
                        text_lower = text.strip().lower()
                        if text_lower in ("restart", "reset", "재시작", "리셋", "/restart", "/reset"):
                            db.set_paused(name, False)
                            mode = "reset" if "reset" in text_lower or "리셋" in text_lower else "resume"
                            db.push_command(name, "restart", f"force,{mode}" if mode != "resume" else "force")
                            await ch.send(msg("pause_unpause_restart", name=name), reply_to=msg_id_str)
                            self._save_offset(bot_id, ch.get_offset() - 1)
                            log(f"{name}: PAUSED → 해제 (텔레그램 명령: {text_lower})")
                            continue
                        await ch.send(msg("paused_hint", name=name), reply_to=msg_id_str)
                        self._save_offset(bot_id, ch.get_offset() - 1)
                        log(f"{name}: PAUSED — 메시지 거부: {text[:50]}")
                        continue

                    # 수신 확인
                    if state.busy:
                        qsize = state.message_queue.qsize() + 1
                        await ch.send(msg("ack_busy", icon=ICON_THINKING, qsize=qsize))
                        log(f"{name}: 수신 확인 전송 (대기 {qsize}건)")
                    else:
                        await ch.send(ICON_THINKING)
                        log(f"{name}: 수신 확인 전송")

                    # update_id 추적 (channel.poll이 offset 자동 관리하므로 현재 offset - 1)
                    update_id = ch.get_offset() - 1

                    await state.message_queue.put({
                        "text": full_text,
                        "msg_id": msg_id,
                        "update_id": update_id,
                        "retry_count": 0,
                        "queued_while_busy": state.busy,
                    })
                    # 큐에 넣은 즉시 offset 갱신 + 파일 저장
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
        self._broadcast_sync(msg("sv_shutting_down"))
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
        log("TeleClaw 종료")


async def main():
    os.makedirs(LOGS_DIR, exist_ok=True)

    existing_pid = _find_existing_teleclaw()
    if existing_pid:
        log(f"이미 실행 중인 TeleClaw 있음 (PID={existing_pid}), 종료")
        print(f"TeleClaw is already running (PID={existing_pid}).")
        sys.exit(42)  # wrapper가 중복 실행 감지용 코드로 인식

    _write_lock()
    hub = TeleClaw()
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

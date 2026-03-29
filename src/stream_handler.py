"""스트림 핸들러 — receive_messages() 루프의 메시지 처리.

AssistantMessage, UserMessage, ResultMessage, SystemMessage,
RateLimitEvent, StreamEvent, TaskStarted/Progress/Notification 처리.

Phase 1: "항상 최신 하나만 edit" 방식.
- edit 대상은 가장 아래 메시지 하나뿐
- 주체(메인/에이전트) 전환 시 현재 메시지 확정 → 새 메시지
"""

import time

from claude_agent_sdk import (
    AssistantMessage, UserMessage, ResultMessage, SystemMessage,
    RateLimitEvent,
    TaskStartedMessage, TaskProgressMessage, TaskNotificationMessage,
)
from claude_agent_sdk.types import StreamEvent

from .logging_utils import log
from .messages import msg
from .agent_display import (
    handle_task_started, handle_task_notification,
    _read_output_file,
)


def tool_summary(tool_name: str, tool_input: dict) -> str:
    """도구 호출을 짧은 이름으로 요약"""
    if tool_name == "Agent":
        desc = (tool_input.get("description") or tool_input.get("prompt", ""))[:50]
        return f"Agent: {desc}" if desc else "Agent"
    short = tool_name
    if short.startswith("mcp__"):
        parts = short[5:].split("__", 1)
        short = ".".join(parts) if len(parts) > 1 else parts[0]
    path = (tool_input.get("file_path") or tool_input.get("path")
            or tool_input.get("pattern") or tool_input.get("command", "")[:60])
    if path:
        path = path.replace("\n", " ").replace("\r", "")
        if len(path) > 40:
            path = "..." + path[-35:]
        return f"{short}: {path}"
    return short


def format_tool_line(tool_lines: list) -> str:
    """도구 호출 목록을 컴팩트한 한 줄로 포맷."""
    names = [t.replace("\U0001f527 ", "") for t in tool_lines]
    if len(names) <= 4:
        return "\u2500 \U0001f527 " + " \u2192 ".join(names)
    shown = names[:2] + [f"...+{len(names) - 3}"] + names[-1:]
    return "\u2500 \U0001f527 " + " \u2192 ".join(shown)


def stabilize_markdown(text: str) -> str:
    """edit 전 미닫힌 코드블록을 임시로 닫아 마크다운 깨짐 방지."""
    if text.count("```") % 2 == 1:
        text += "\n```"
    return text


class StreamContext:
    """receive_messages() 루프에서 공유하는 상태."""
    __slots__ = (
        "live_msg_id", "live_lines", "tool_lines", "last_tool_name",
        "last_block_type", "msg_count", "last_edit", "edit_interval",
        "query_start", "consecutive_edit_fails", "last_progress_notify",
        "agent_tasks", "retry_count", "_tool_id_map",
        "current_source", "_agent_status_lines",
    )

    def __init__(self):
        self.live_msg_id = ""
        self.live_lines = []
        self.tool_lines = []
        self.last_tool_name = ""
        self._tool_id_map = {}
        self.last_block_type = ""
        self.msg_count = 0
        self.last_edit = 0.0
        self.edit_interval = 1.0
        self.query_start = time.time()
        self.consecutive_edit_fails = 0
        self.last_progress_notify = 0
        self.agent_tasks = {}
        self.retry_count = 0
        self.current_source = "main"
        self._agent_status_lines = {}  # task_id → 진행 상태 문자열


# ── 메시지 관리 ──


async def _freeze_and_new(ch, ctx: StreamContext, new_source: str, header: str | None):
    """현재 메시지를 확정(freeze)하고 새 주체의 메시지를 준비."""
    if ctx.live_msg_id:
        if ctx.tool_lines:
            ctx.live_lines.append(format_tool_line(ctx.tool_lines))
        content = "\n".join(ctx.live_lines)
        if content.strip():
            await ch.edit(ctx.live_msg_id, ch.format(content), use_markup=True)
    old = ctx.current_source
    ctx.live_msg_id = ""
    ctx.live_lines = []
    ctx.tool_lines = []
    ctx.current_source = new_source
    ctx._agent_status_lines = {}
    if header:
        ctx.live_lines.append(header)
    log(f"[freeze] {old} → {new_source}" + (f" header={header}" if header else ""))


async def _send_or_edit(ch, ctx: StreamContext):
    """live 메시지 send/edit. 항상 가장 아래 메시지 하나만 edit."""
    content = _build_display(ctx)
    if not content.strip():
        return
    now = time.time()

    if not ctx.live_msg_id:
        # 첫 메시지 → 즉시 send
        ctx.live_msg_id = await ch.send(ch.format(content), use_markup=True)
        ctx.last_edit = now
    elif now - ctx.last_edit >= ctx.edit_interval:
        # 4096자 초과 → 확정 후 새 메시지
        if len(content) > 4096 - 50:
            await _freeze_and_new(ch, ctx, ctx.current_source, None)
            last_line = content.split("\n")[-1] if content else ""
            if last_line:
                ctx.live_lines = [last_line]
                ctx.live_msg_id = await ch.send(last_line)
                ctx.last_edit = now
        else:
            stable = ch.format(content)
            ok = await ch.edit(ctx.live_msg_id, stable, use_markup=True)
            if not ok:
                ctx.consecutive_edit_fails += 1
                if ctx.consecutive_edit_fails >= 3:
                    ctx.edit_interval = min(ctx.edit_interval * 2, 5.0)
                    ctx.consecutive_edit_fails = 0
                ctx.live_msg_id = await ch.send(stable, use_markup=True)
            else:
                ctx.consecutive_edit_fails = 0
                if ctx.edit_interval > 1.0:
                    ctx.edit_interval = max(ctx.edit_interval - 0.5, 1.0)
            ctx.last_edit = now


def _build_display(ctx: StreamContext) -> str:
    """live_lines + tool_lines + 에이전트 진행 상태를 합쳐 표시 문자열 생성."""
    display = list(ctx.live_lines)
    if ctx.tool_lines:
        display.append(format_tool_line(ctx.tool_lines))
    if ctx._agent_status_lines:
        status = " | ".join(ctx._agent_status_lines.values())
        display.append(status)
    return "\n".join(display)


# ── 메시지 타입별 처리 ──


async def process_assistant_message(sdk_msg, state, ch, ctx: StreamContext, output_level: str):
    """AssistantMessage 처리 — TextBlock, ToolUseBlock, ThinkingBlock."""
    from claude_agent_sdk import TextBlock, ToolUseBlock, ThinkingBlock
    _lvl = output_level
    for block in sdk_msg.content:
        if isinstance(block, TextBlock) and block.text.strip():
            # 메인 응답 텍스트 — 에이전트 주체였으면 전환
            if ctx.current_source != "main":
                await _freeze_and_new(ch, ctx, "main", None)
            if ctx.tool_lines:
                ctx.live_lines.append(format_tool_line(ctx.tool_lines))
                ctx.tool_lines = []
            if ctx.last_block_type and ctx.last_block_type != "text":
                ctx.live_lines.append("")
            ctx.live_lines.append(block.text)
            ctx.last_block_type = "text"
            log(f"{state.name}: [block] TextBlock ({len(block.text)}자): {block.text[:200]}")
        elif isinstance(block, ToolUseBlock):
            tool_name = block.name
            tool_input = block.input
            ctx.last_tool_name = tool_name
            block_id = getattr(block, "id", "")
            if block_id:
                ctx._tool_id_map[block_id] = tool_name
            if tool_name == "Agent" and block_id:
                if not hasattr(state, "_pending_agent_tool_ids"):
                    state._pending_agent_tool_ids = set()
                state._pending_agent_tool_ids.add(block_id)
                log(f"{state.name}: [agent] tool_use_id 등록: {block_id[:16]}")
            if _lvl != "minimal":
                if ctx.last_block_type and ctx.last_block_type != "tool" and not ctx.tool_lines:
                    ctx.live_lines.append("")
                summary = tool_summary(tool_name, tool_input)
                ctx.tool_lines.append(f"\U0001f527 {summary}")
            ctx.last_block_type = "tool"
            log(f"{state.name}: [block] ToolUse: {tool_summary(tool_name, tool_input).replace(chr(10), ' ')}")
        elif isinstance(block, ThinkingBlock):
            log(f"{state.name}: [block] Thinking ({len(block.thinking or '')}자)")
            continue
        else:
            log(f"{state.name}: [block] {type(block).__name__} (skip)")
            continue

        await _send_or_edit(ch, ctx)


async def process_user_message(sdk_msg, state, ch, ctx: StreamContext):
    """UserMessage 처리 — ToolResultBlock에서 결과 추출."""
    from claude_agent_sdk import ToolResultBlock, TextBlock
    result_text = ""
    result_tool_use_id = ""

    content_blocks = sdk_msg.content if isinstance(sdk_msg.content, list) else []
    for block in content_blocks:
        if isinstance(block, ToolResultBlock):
            content = block.content
            result_tool_use_id = getattr(block, "tool_use_id", "") or ""
            if isinstance(content, str):
                result_text = content.strip()
            elif isinstance(content, list):
                parts = [x.get("text", "") for x in content if isinstance(x, dict) and x.get("text")]
                result_text = "\n".join(parts).strip()
            log(f"{state.name}: [user-block] ToolResultBlock ({len(result_text)}자)")
            break
        elif isinstance(block, TextBlock) and block.text:
            result_text = block.text.strip()
            log(f"{state.name}: [user-block] TextBlock ({len(result_text)}자)")
            break

    # tool_use_result 필드 폴백
    if not result_text:
        tur = getattr(sdk_msg, "tool_use_result", None)
        if tur:
            if isinstance(tur, dict):
                result_text = str(tur.get("result", "") or tur.get("content", "")).strip()
            elif isinstance(tur, str):
                result_text = tur.strip()
            else:
                r = getattr(tur, "result", None) or getattr(tur, "content", None)
                if r:
                    result_text = str(r).strip()
            if result_text:
                log(f"{state.name}: [user-block] tool_use_result ({len(result_text)}자)")

    # tool_use_id → tool_name 역매핑
    if result_tool_use_id and result_tool_use_id in ctx._tool_id_map:
        mapped_name = ctx._tool_id_map[result_tool_use_id]
        if mapped_name != ctx.last_tool_name:
            ctx.last_tool_name = mapped_name

    # Agent 결과: 임시 저장 (TaskNotification에서 표시)
    pending_ids = getattr(state, "_pending_agent_tool_ids", set())
    is_agent_result = result_tool_use_id and result_tool_use_id in pending_ids
    if is_agent_result:
        pending_ids.discard(result_tool_use_id)
        state._pending_agent_results = getattr(state, "_pending_agent_results", {})
        state._pending_agent_results[result_tool_use_id] = result_text
        log(f"{state.name}: [agent] 결과 임시 저장 ({len(result_text)}자, tuid={result_tool_use_id[:16]})")
        result_text = ""
    elif ctx.last_tool_name == "Agent" and result_text:
        log(f"{state.name}: [agent] 프롬프트/결과 스킵 ({len(result_text)}자)")
        result_text = ""

    if result_text:
        log(f"{state.name}: [user] result_text={len(result_text)}자 last_tool={ctx.last_tool_name}")
        if ctx.last_tool_name in ("Edit", "Write", "NotebookEdit", "Read", "Grep", "Glob"):
            if ctx.tool_lines:
                ctx.tool_lines[-1] += f" ({len(result_text)}자)"
        elif len(result_text) <= 500:
            if ctx.tool_lines:
                ctx.live_lines.append(format_tool_line(ctx.tool_lines))
                ctx.tool_lines = []
            ctx.live_lines.append(result_text)
        else:
            if ctx.tool_lines:
                ctx.tool_lines[-1] += f" ({len(result_text)}자)"

        await _send_or_edit(ch, ctx)


async def process_system_message(sdk_msg, state, ch, ctx: StreamContext):
    """SystemMessage 처리."""
    subtype = sdk_msg.subtype
    if subtype == "api_retry":
        ctx.retry_count += 1
        log(f"{state.name}: [system] api_retry ({ctx.retry_count}회)")
        if ctx.retry_count == 10:
            await ch.send(msg("api_retry_notify"))
    else:
        ctx.retry_count = 0
        log(f"{state.name}: [system] subtype={subtype}")


async def process_rate_limit(sdk_msg, state, ch):
    """RateLimitEvent 처리."""
    info = sdk_msg.rate_limit_info
    log(f"{state.name}: [rate_limit] status={info.status} type={info.rate_limit_type} resets={info.resets_at}")
    if info.status != "allowed":
        now = time.time()
        if now - state.last_notify_time > 60:
            state.last_notify_time = now
            await ch.send(f"\u26a0 {state.name}: rate limit ({info.rate_limit_type}, resets={info.resets_at})")


# ── 메인 디스패처 ──


async def process_stream_message(sdk_msg, state, ch, ctx: StreamContext, output_level: str, save_session_ids_fn):
    """단일 SDK 메시지를 처리. ResultMessage이면 True 반환 (루프 종료 신호)."""
    if isinstance(sdk_msg, AssistantMessage):
        await process_assistant_message(sdk_msg, state, ch, ctx, output_level)

    elif isinstance(sdk_msg, UserMessage):
        await process_user_message(sdk_msg, state, ch, ctx)

    elif isinstance(sdk_msg, ResultMessage):
        if sdk_msg.session_id:
            state.session_id = sdk_msg.session_id
            save_session_ids_fn()
        if sdk_msg.usage:
            log(f"{state.name}: [usage] {sdk_msg.usage}")

        result_text = (sdk_msg.result or "").strip()
        if not ctx.live_lines and result_text:
            ctx.live_lines.append(result_text)
            log(f"{state.name}: [result-fallback] {len(result_text)}자")

        log(f"{state.name}: [ResultMessage] last_tool={ctx.last_tool_name} result_len={len(result_text)}")
        if sdk_msg.total_cost_usd:
            log(f"{state.name}: [cost] ${sdk_msg.total_cost_usd:.4f}")
        return True

    elif isinstance(sdk_msg, TaskStartedMessage):
        handle_task_started(sdk_msg, ctx.agent_tasks, state)
        agent_desc = sdk_msg.description or "Agent"
        ctx._agent_status_lines[sdk_msg.task_id] = f"\u23f3 {agent_desc}: 시작..."
        await _send_or_edit(ch, ctx)
        log(f"{state.name}: [agent] started: {agent_desc}")

    elif isinstance(sdk_msg, TaskProgressMessage):
        task = ctx.agent_tasks.get(sdk_msg.task_id)
        if task:
            tool_count = getattr(sdk_msg.usage, "tool_uses", 0) if sdk_msg.usage else 0
            task["tool_count"] = tool_count
            last_tool = sdk_msg.last_tool_name or ""
            desc = task["description"]
            ctx._agent_status_lines[sdk_msg.task_id] = f"\u23f3 {desc}: \U0001f527 {tool_count}개 도구" + (f" ({last_tool})" if last_tool else "")
            await _send_or_edit(ch, ctx)
        log(f"{state.name}: [agent] progress: task={sdk_msg.task_id[:8]}")

    elif isinstance(sdk_msg, TaskNotificationMessage):
        handle_task_notification(sdk_msg, ctx.agent_tasks, state)
        task_id = sdk_msg.task_id
        ctx._agent_status_lines.pop(task_id, None)

        comp = state._completed_agents.get(task_id)
        if comp and comp.get("status") == "completed":
            result_text = ""
            output_file = comp.get("output_file", "")
            if output_file:
                result_text = _read_output_file(output_file)
            if not result_text:
                result_text = comp.get("summary", "")
            if not result_text:
                tuid = comp.get("tool_use_id", "")
                pending = getattr(state, "_pending_agent_results", {})
                result_text = pending.pop(tuid, "")
            if result_text:
                for marker in ("agentId:", "<usage>", "total_tokens:"):
                    idx = result_text.find(marker)
                    if idx > 0:
                        result_text = result_text[:idx].rstrip()
                preview = result_text[:300] + ("..." if len(result_text) > 300 else "")
                desc = comp.get("description", "Agent")
                icon = comp.get("icon", "\U0001f50d")  # 🔍
                await _freeze_and_new(ch, ctx, f"agent:{task_id}", f"{icon} {desc}:")
                ctx.live_lines.append(preview)
                await _send_or_edit(ch, ctx)
                log(f"{state.name}: [agent] 결과 표시 ({len(result_text)}자, {desc})")
            else:
                desc = comp.get("description", "Agent")
                log(f"{state.name}: [agent] 결과 없음 ({desc})")
            state._completed_agents.pop(task_id, None)

    elif isinstance(sdk_msg, SystemMessage):
        await process_system_message(sdk_msg, state, ch, ctx)

    elif isinstance(sdk_msg, RateLimitEvent):
        await process_rate_limit(sdk_msg, state, ch)

    elif isinstance(sdk_msg, StreamEvent):
        log(f"{state.name}: [stream] event={sdk_msg.event}")

    return False


async def finalize_response(state, ch, ctx: StreamContext):
    """응답 완료 후 최종 전송."""
    if ctx.tool_lines:
        ctx.live_lines.append(format_tool_line(ctx.tool_lines))
    if ctx.live_lines:
        content = "\n".join(ctx.live_lines)
        chunks = [ch.format(c) for c in ch.split(content)]
        if ctx.live_msg_id:
            ok = await ch.edit(ctx.live_msg_id, chunks[0], use_markup=True)
            if not ok:
                await ch.edit(ctx.live_msg_id, ch.split(content)[0])
            for chunk in chunks[1:]:
                await ch.send(chunk, use_markup=True)
        else:
            for chunk in chunks:
                await ch.send(chunk, use_markup=True)
        log(f"{state.name}: 최종 전송 ({len(content)}자, {len(chunks)}청크)")
    else:
        log(f"{state.name}: 빈 응답")
        await ch.send(msg("empty_response"))

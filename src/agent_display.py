"""에이전트 대화 표시 — TaskStarted/Progress/Notification 처리 및 결과 매칭."""

import json
import os

from .config import ICON_DONE
from .logging_utils import log
from .messages import msg


def _read_output_file(path: str, log_fn=log) -> str:
    """에이전트 output 파일(JSON lines)을 파싱하여 최종 결과를 반환. 실패 시 빈 문자열."""
    if not path:
        return ""
    try:
        # Windows 경로 정규화
        norm = os.path.normpath(path)
        if not os.path.isfile(norm):
            log_fn(f"[agent] output 파일 없음: {norm}")
            return ""
        with open(norm, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read().strip()
        if not raw:
            return ""
        lines = raw.splitlines()
        last_result = None
        last_assistant = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            obj_type = obj.get("type")
            if obj_type == "result":
                last_result = obj
            elif obj_type == "assistant":
                last_assistant = obj
        # 1) "type":"result" → "result" 필드
        if last_result:
            text = last_result.get("result", "")
            if text:
                return text
        # 2) "type":"assistant" → content 내 TextBlock의 text
        if last_assistant:
            content = (last_assistant.get("message") or {}).get("content")
            if isinstance(content, list):
                # 역순으로 마지막 text 블록 찾기
                for block in reversed(content):
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            return text
            elif isinstance(content, str) and content:
                return content
        return ""
    except Exception as exc:
        log_fn(f"[agent] output 파일 읽기 실패: {exc}")
    return ""


def handle_task_started(sdk_msg, agent_tasks: dict, state, log_fn=log):
    """TaskStartedMessage 처리 — agent_tasks와 state._active_agents에 등록."""
    prompt = getattr(sdk_msg, "data", {}).get("prompt", "") or ""
    desc = sdk_msg.description or ""
    agent_name = desc.split(":")[0].strip() if ":" in desc else desc[:50]
    tool_use_id = getattr(sdk_msg, "tool_use_id", "") or ""
    task_info = {
        "description": agent_name,
        "prompt": prompt[:200] + ("..." if len(prompt) > 200 else ""),
        "msg_id": "",
        "tool_count": 0,
        "tool_use_id": tool_use_id,
    }
    agent_tasks[sdk_msg.task_id] = task_info
    state._active_agents[sdk_msg.task_id] = task_info
    log_fn(f"{state.name}: [agent] started: {desc} (task={sdk_msg.task_id[:8]})")


async def handle_task_progress(sdk_msg, agent_tasks: dict, ch, log_fn=log):
    """TaskProgressMessage 처리 — 진행 상태 텔레그램 전송/수정."""
    task = agent_tasks.get(sdk_msg.task_id)
    if task:
        task["tool_count"] = getattr(sdk_msg.usage, "tool_uses", 0) if sdk_msg.usage else 0
        last_tool = sdk_msg.last_tool_name or ""
        progress_text = msg("agent_progress",
            description=task['description'],
            prompt=task.get('prompt', ''),
            tool_count=task['tool_count'],
            last_tool=last_tool)
        if task["msg_id"]:
            await ch.edit(task["msg_id"], progress_text)
        else:
            task["msg_id"] = await ch.send(progress_text)
    log_fn(f"{getattr(ch, 'bot_name', '?')}: [agent] progress: task={sdk_msg.task_id[:8]} tools={task['tool_count'] if task else '?'}")


def handle_task_notification(sdk_msg, agent_tasks: dict, state, log_fn=log):
    """TaskNotificationMessage 처리 — completed_agents에 등록."""
    task = agent_tasks.pop(sdk_msg.task_id, None)
    # agent_tasks에 없으면 _active_agents에서 폴백
    if not task:
        task = state._active_agents.get(sdk_msg.task_id)
    status = sdk_msg.status
    icon = "\U0001f50d" if status == "completed" else "\u274c" if status == "failed" else "\u23f9"  # 🔍 완료 / ❌ 실패 / ⏹ 중단
    desc = task['description'] if task else 'Agent'
    prompt = task.get('prompt', '') if task else ''
    msg_id = task["msg_id"] if task and task.get("msg_id") else ""
    # SDK tool_use_id 우선, 없으면 task에서 저장된 값 사용
    tool_use_id = getattr(sdk_msg, "tool_use_id", "") or ""
    if not tool_use_id and task:
        tool_use_id = task.get("tool_use_id", "")
    output_file = getattr(sdk_msg, "output_file", "") or ""
    summary = getattr(sdk_msg, "summary", "") or ""
    state._completed_agents[sdk_msg.task_id] = {
        "msg_id": msg_id, "description": desc, "prompt": prompt, "icon": icon, "status": status,
        "tool_use_id": tool_use_id,
        "output_file": output_file,
        "summary": summary,
    }
    # _active_agents 정리
    state._active_agents.pop(sdk_msg.task_id, None)
    # 임시 저장된 결과가 있으면 바로 매칭 (ToolResultBlock이 notification보다 먼저 온 경우)
    pending_results = getattr(state, "_pending_agent_results", {})
    if tool_use_id and tool_use_id in pending_results:
        state._completed_agents[sdk_msg.task_id]["_pending_result"] = pending_results.pop(tool_use_id)
        log_fn(f"{state.name}: [agent] 임시 결과 연결됨 (tuid={tool_use_id[:16]})")
    log_fn(f"{state.name}: [agent] {status}: {desc} (tuid={tool_use_id[:16] if tool_use_id else 'none'}, output_file={'Y' if output_file else 'N'}, summary={'Y' if summary else 'N'})")


async def try_resolve_from_output(task_id: str, state, ch, log_fn=log):
    """TaskNotification의 output_file 또는 summary로 에이전트 결과를 직접 표시.

    output_file → 파일 읽기 → 성공 시 결과 표시 및 completed_agents에서 제거.
    output_file 없거나 실패 시 summary 사용.
    둘 다 없으면 False (기존 ToolResultBlock 매칭으로 폴백).
    """
    comp = state._completed_agents.get(task_id)
    if not comp or comp.get("status") != "completed":
        return False

    result_text = ""
    # 1) output_file에서 직접 읽기
    output_file = comp.get("output_file", "")
    if output_file:
        result_text = _read_output_file(output_file, log_fn)
        if result_text:
            log_fn(f"{state.name}: [agent] output 파일에서 결과 읽음 ({len(result_text)}자)")

    # 2) output_file 없거나 빈 경우 summary 사용
    if not result_text:
        result_text = comp.get("summary", "")
        if result_text:
            log_fn(f"{state.name}: [agent] summary에서 결과 사용 ({len(result_text)}자)")

    if not result_text:
        return False

    # 결과 표시 — match_agent_result과 동일한 로직
    clean = result_text
    for marker in ("agentId:", "<usage>", "total_tokens:"):
        idx = clean.find(marker)
        if idx > 0:
            clean = clean[:idx].rstrip()
    preview = clean[:300] + ("..." if len(clean) > 300 else "")
    icon = comp.get("icon", ICON_DONE)
    final_text = msg("agent_result",
        description=comp.get("description", "Agent"),
        prompt=comp.get("prompt", ""),
        preview=preview, icon=icon)
    if comp.get("msg_id"):
        await ch.edit(comp["msg_id"], final_text)
    else:
        await ch.send(final_text)
    log_fn(f"{state.name}: [agent] output 직접 표시 완료 (msg_id={'edit' if comp.get('msg_id') else 'new'})")
    del state._completed_agents[task_id]
    return True


async def match_agent_result(result_text: str, state, ch, log_fn=log, tool_use_id: str = ""):
    """UserMessage의 ToolResult에서 Agent 결과를 completed_agents에 매칭.
    매칭 성공 시 True 반환, 실패 시 False."""
    if not result_text or not state._completed_agents:
        return False
    # tool_use_id로 정확히 매칭, 없으면 첫 번째 미할당 에이전트
    matched_tid = None
    if tool_use_id:
        for tid, comp in state._completed_agents.items():
            if comp.get("tool_use_id") == tool_use_id and "result" not in comp:
                matched_tid = tid
                log_fn(f"{state.name}: [agent] tool_use_id 정확 매칭: {tool_use_id[:16]}")
                break
    if not matched_tid:
        log_fn(f"{state.name}: [agent] 매칭 실패: completed={len(state._completed_agents)}건, tuid={tool_use_id[:16] if tool_use_id else 'none'}")
        return False
    comp = state._completed_agents[matched_tid]
    clean = result_text
    for marker in ("agentId:", "<usage>", "total_tokens:"):
        idx = clean.find(marker)
        if idx > 0:
            clean = clean[:idx].rstrip()
    preview = clean[:300] + ("..." if len(clean) > 300 else "")
    icon = comp.get("icon", ICON_DONE)
    final_text = msg("agent_result",
        description=comp.get("description", "Agent"),
        prompt=comp.get("prompt", ""),
        preview=preview, icon=icon)
    if comp.get("msg_id"):
        await ch.edit(comp["msg_id"], final_text)
    else:
        # progress 메시지가 없었던 경우 (빠른 에이전트) → 새 메시지로 전송
        await ch.send(final_text)
    log_fn(f"{state.name}: [agent] result added ({len(result_text)}자, msg_id={'edit' if comp.get('msg_id') else 'new'})")
    del state._completed_agents[matched_tid]
    return True

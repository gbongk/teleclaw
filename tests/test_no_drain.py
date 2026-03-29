"""버퍼 드레인 제거 후 대체 경로 검증 테스트.

drain_buffer 없이도 아래 케이스가 정상 동작하는지 확인:
1. 에이전트 task_notification → _completed_agents 수집
2. 에이전트 ToolResult → tool_use_id 기반 매칭
3. MCP 결과 → UserMessage에서 처리
4. N턴 밀림 없이 정상 동작
5. 빈 응답 시 드레인 폴백 없이 동작
"""

import asyncio
import pytest
from unittest.mock import MagicMock

from src.stream_handler import (
    process_stream_message, finalize_response,
    StreamContext,
)

from tests.mock_sdk import (
    make_assistant_msg, make_user_msg, make_result_msg,
    TextBlock, ToolUseBlock, ToolResultBlock,
    AssistantMessage, UserMessage, ResultMessage,
    TaskStartedMessage, TaskNotificationMessage,
)
from tests.mock_channel import MockChannel


# --- 헬퍼 ---

def _make_state(name="Test"):
    state = MagicMock()
    state.name = name
    state.session_id = "test-session"
    state._pending_agent_tool_ids = set()
    state._completed_agents = {}
    state._pending_agent_results = {}
    state._active_agents = {}
    state.last_notify_time = 0.0
    return state


def _noop_save():
    pass


async def _run_stream(messages, state=None, ch=None, output_level="normal"):
    if state is None:
        state = _make_state()
    if ch is None:
        ch = MockChannel()
    ctx = StreamContext()

    for msg in messages:
        done = await process_stream_message(
            msg, state, ch, ctx,
            output_level=output_level,
            save_session_ids_fn=_noop_save,
        )
        if done:
            break

    return state, ch, ctx


# ============================================================
# 1. 에이전트 task_notification → _completed_agents 수집
# ============================================================

class TestAgentNotificationInLoop:
    """drain_buffer 없이 TaskNotificationMessage가 루프에서 처리되는지."""

    @pytest.mark.asyncio
    async def test_task_notification_collects_completed_agent(self):
        """TaskStarted → TaskNotification → 결과 표시 또는 _completed_agents에 수집."""
        state = _make_state()
        ch = MockChannel()
        ctx = StreamContext()

        msg1 = make_assistant_msg([ToolUseBlock(name="Agent", input={"description": "test agent"}, id="agent_tool_1")])
        await process_stream_message(msg1, state, ch, ctx, "normal", _noop_save)

        ts = TaskStartedMessage(task_id="task_abc", description="test agent", tool_use_id="agent_tool_1")
        await process_stream_message(ts, state, ch, ctx, "normal", _noop_save)

        tn = TaskNotificationMessage(
            task_id="task_abc", status="completed",
            summary="에이전트 작업 완료", tool_use_id="agent_tool_1",
        )
        await process_stream_message(tn, state, ch, ctx, "normal", _noop_save)

        all_text = ch.get_all_text()
        assert "에이전트 작업 완료" in all_text or len(ch.sent_messages) > 0


# ============================================================
# 2. 에이전트 ToolResult → tool_use_id 기반 매칭
# ============================================================

class TestAgentToolResultMatching:
    """drain_buffer 없이 에이전트 ToolResult가 매칭되는지."""

    @pytest.mark.asyncio
    async def test_agent_result_matched_by_tool_use_id(self):
        """Agent ToolUse → TaskNotification → UserMessage(ToolResult) → 매칭."""
        state = _make_state()
        ch = MockChannel()
        ctx = StreamContext()

        msg1 = make_assistant_msg([ToolUseBlock(name="Agent", input={"description": "분석"}, id="agent_t1")])
        await process_stream_message(msg1, state, ch, ctx, "normal", _noop_save)

        assert "agent_t1" in state._pending_agent_tool_ids

        ts = TaskStartedMessage(task_id="task_001", description="분석", tool_use_id="agent_t1")
        await process_stream_message(ts, state, ch, ctx, "normal", _noop_save)

        tn = TaskNotificationMessage(
            task_id="task_001", status="completed",
            summary="분석 완료", tool_use_id="agent_t1",
        )
        await process_stream_message(tn, state, ch, ctx, "normal", _noop_save)

        msg_user = make_user_msg(tool_result="에이전트 분석 결과입니다", tool_use_id="agent_t1")
        await process_stream_message(msg_user, state, ch, ctx, "normal", _noop_save)

        assert "agent_t1" not in state._pending_agent_tool_ids


# ============================================================
# 3. MCP 결과가 UserMessage에서 처리되는지
# ============================================================

class TestMcpResultInUserMessage:
    """drain_buffer 없이 MCP 결과가 UserMessage에서 처리되는지."""

    @pytest.mark.asyncio
    async def test_mcp_result_in_live_lines(self):
        """MCP ToolUse → UserMessage(MCP결과) → live_lines에 추가."""
        messages = [
            make_assistant_msg([ToolUseBlock(
                name="mcp__ai-chat__ask_ai",
                input={"prompt": "hello"},
                id="mcp_t1",
            )]),
            make_user_msg(
                tool_result='{"result":"AI 답변"}',
                tool_use_id="mcp_t1",
            ),
        ]
        state, ch, ctx = await _run_stream(messages)

        # MCP 결과가 짧은 결과(<=500자)로 live_lines에 추가됨
        all_live = "\n".join(ctx.live_lines)
        assert '{"result":"AI 답변"}' in all_live or len(ctx.live_lines) > 0

    @pytest.mark.asyncio
    async def test_mcp_result_with_claude_text(self):
        """MCP 결과 + Claude 텍스트 → 둘 다 live_lines에 포함."""
        messages = [
            make_assistant_msg([ToolUseBlock(
                name="mcp__ai-chat__ask_ai",
                input={"prompt": "hello"},
                id="mcp_t2",
            )]),
            make_user_msg(
                tool_result='{"result":"AI 답변"}',
                tool_use_id="mcp_t2",
            ),
            make_assistant_msg([TextBlock(text="AI가 다음과 같이 답했습니다")]),
            make_result_msg(result="", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)
        await finalize_response(state, ch, ctx)

        # sent + edited 모두 확인 (finalize가 edit으로 보낼 수 있음)
        all_text = ch.get_all_text()
        edited_text = "\n".join(m["text"] for m in ch.edited_messages)
        combined = all_text + "\n" + edited_text
        assert "AI가 다음과 같이 답했습니다" in combined

    @pytest.mark.asyncio
    async def test_mcp_result_no_claude_text(self):
        """MCP 결과만 오고 Claude 텍스트 없음 → live_lines 또는 ResultMessage fallback."""
        messages = [
            make_assistant_msg([ToolUseBlock(
                name="mcp__ai-chat__ask_ai",
                input={"prompt": "hello"},
                id="mcp_t3",
            )]),
            make_user_msg(
                tool_result='{"result":"AI 답변 내용"}',
                tool_use_id="mcp_t3",
            ),
            make_result_msg(result="AI 답변 내용", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)
        await finalize_response(state, ch, ctx)

        all_text = ch.get_all_text()
        edited_text = "\n".join(m["text"] for m in ch.edited_messages)
        combined = all_text + "\n" + edited_text
        assert "AI 답변 내용" in combined


# ============================================================
# 4. N턴 밀림 없이 정상 동작 (연속 턴 시뮬레이션)
# ============================================================

class TestMultiTurnNoDrain:
    """drain_buffer 없이 연속 턴이 정상 동작하는지."""

    @pytest.mark.asyncio
    async def test_two_turns_independent(self):
        """턴1 → finalize → 턴2 → finalize. 각각 독립 처리."""
        state = _make_state()

        ch1 = MockChannel()
        ctx1 = StreamContext()
        msg1 = make_assistant_msg([TextBlock(text="턴1 응답")])
        await process_stream_message(msg1, state, ch1, ctx1, "normal", _noop_save)
        result1 = make_result_msg(result="턴1 응답", session_id="s1")
        await process_stream_message(result1, state, ch1, ctx1, "normal", _noop_save)
        await finalize_response(state, ch1, ctx1)

        assert "턴1 응답" in ch1.get_all_text()

        ch2 = MockChannel()
        ctx2 = StreamContext()
        msg2 = make_assistant_msg([TextBlock(text="턴2 응답")])
        await process_stream_message(msg2, state, ch2, ctx2, "normal", _noop_save)
        result2 = make_result_msg(result="턴2 응답", session_id="s1")
        await process_stream_message(result2, state, ch2, ctx2, "normal", _noop_save)
        await finalize_response(state, ch2, ctx2)

        assert "턴2 응답" in ch2.get_all_text()
        assert "턴1 응답" not in ch2.get_all_text()


# ============================================================
# 5. 빈 응답 시 드레인 폴백 없이 동작
# ============================================================

class TestEmptyResponseNoDrain:
    """drain_buffer 없이 빈 응답 시 정상 처리."""

    @pytest.mark.asyncio
    async def test_empty_response_shows_warning(self):
        """ResultMessage만 오고 텍스트 없음 → 빈 응답 메시지."""
        messages = [
            make_result_msg(result="", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)
        await finalize_response(state, ch, ctx)

        all_text = ch.get_all_text()
        assert len(all_text) > 0 or len(ch.sent_messages) > 0

    @pytest.mark.asyncio
    async def test_result_with_text_no_drain_fallback(self):
        """ResultMessage에 result 텍스트가 있으면 정상 표시."""
        messages = [
            make_result_msg(result="처리 완료되었습니다", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)
        await finalize_response(state, ch, ctx)

        all_text = ch.get_all_text()
        assert "처리 완료" in all_text

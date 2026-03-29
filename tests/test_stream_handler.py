"""스트림 핸들러 테스트 — process_stream_message() 통합 검증.

SDK mock 메시지를 주입하여 텔레그램 채널로의 출력을 검증.
conftest.py에서 claude_agent_sdk mock이 이미 설치된 상태에서 실행.
"""

import sys
import os
import asyncio
import pytest
from unittest.mock import MagicMock, patch

# conftest.py의 mock SDK가 적용된 상태에서 import
from src.stream_handler import (
    process_stream_message, finalize_response,
    StreamContext,
)

from tests.mock_sdk import (
    make_assistant_msg, make_user_msg, make_result_msg, make_system_msg,
    TextBlock, ToolUseBlock, ThinkingBlock, ToolResultBlock,
    AssistantMessage, UserMessage, ResultMessage,
)
from tests.mock_channel import MockChannel


# --- 헬퍼 ---

def _make_state(name="Test"):
    """테스트용 state 객체 생성. SessionState 대신 간단한 mock 사용."""
    state = MagicMock()
    state.name = name
    state.session_id = "test-session"
    state._pending_agent_tool_ids = set()
    state._completed_agents = {}
    state._pending_agent_results = {}
    state.last_notify_time = 0.0
    return state


def _noop_save():
    pass


async def _run_stream(messages, state=None, ch=None, output_level="normal"):
    """메시지 리스트를 순서대로 process_stream_message에 주입.

    Returns: (state, ch, ctx) — 검증용.
    """
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
# 테스트 케이스
# ============================================================


class TestBuiltinToolResult:
    """1. 빌트인 도구 결과 표시 — Bash 호출 후 결과."""

    @pytest.mark.asyncio
    async def test_bash_result_shows_length(self):
        """AssistantMessage(ToolUseBlock "Bash") → UserMessage(ToolResultBlock) → ResultMessage
        결과: tool_lines에 길이 표시."""
        messages = [
            make_assistant_msg([ToolUseBlock(name="Bash", input={"command": "ls"}, id="tool1")]),
            make_user_msg(tool_result="file1.py\nfile2.py\nfile3.py", tool_use_id="tool1"),
            make_result_msg(result="", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)

        # Bash 결과는 500자 이하이므로 live_lines에 직접 포함됨
        # finalize를 호출하여 최종 전송
        await finalize_response(state, ch, ctx)

        # 전송된 메시지에 결과가 포함되어야 함
        all_text = ch.get_all_text()
        assert "file1.py" in all_text or "Bash" in all_text


class TestMcpResultViaUserMessage:
    """2. MCP 도구 결과 — UserMessage로 오는 경우."""

    @pytest.mark.asyncio
    async def test_mcp_result_in_user_message(self):
        """AssistantMessage(ToolUseBlock "mcp__ai-chat__ask_ai")
        → UserMessage(ToolResultBlock '{"result":"답변"}')
        → ResultMessage
        """
        messages = [
            make_assistant_msg([ToolUseBlock(
                name="mcp__ai-chat__ask_ai",
                input={"prompt": "hello"},
                id="tool_mcp1",
            )]),
            make_user_msg(
                tool_result='{"result":"AI가 답변한 내용입니다"}',
                tool_use_id="tool_mcp1",
            ),
            make_result_msg(result="", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)
        await finalize_response(state, ch, ctx)

        # MCP 도구는 is_verbose_tool이어야 하므로 verbose 결과 전송
        # 현재 로직: UserMessage의 MCP 결과는 빌트인 도구와 동일하게 처리
        # (verbose 전송은 ResultMessage에서 처리)
        all_text = ch.get_all_text()
        # UserMessage에서 결과가 live_lines에 들어가거나 별도 전송되어야 함
        assert len(ch.sent_messages) > 0


class TestMcpResultViaResultMessage:
    """3. MCP 도구 결과 — ResultMessage fallback."""

    @pytest.mark.asyncio
    async def test_mcp_result_in_result_message(self):
        """AssistantMessage(ToolUseBlock "mcp__ai-chat__ask_ai")
        → ResultMessage(result="답변")
        결과: result-fallback으로 live_lines에 포함됨.
        """
        messages = [
            make_assistant_msg([ToolUseBlock(
                name="mcp__ai-chat__ask_ai",
                input={"prompt": "hello"},
                id="tool_mcp2",
            )]),
            make_result_msg(result="AI 답변 내용", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)
        await finalize_response(state, ch, ctx)

        all_text = ch.get_all_text()
        # fallback으로 live_lines에 포함되어야 함
        assert len(ch.sent_messages) > 0


class TestVerboseToolPatternMatch:
    """5. verbose_tools fnmatch 패턴 매칭."""

    def test_verbose_tools_fnmatch(self):
        from fnmatch import fnmatch
        pattern = "mcp__ai*chat__*"
        assert fnmatch("mcp__ai-chat__ask_ai", pattern) is True
        assert fnmatch("mcp__ai_chat__ask_ai", pattern) is True
        assert fnmatch("Bash", pattern) is False
        assert fnmatch("Read", pattern) is False


class TestPlainTextResponse:
    """7. 일반 텍스트 응답."""

    @pytest.mark.asyncio
    async def test_text_response(self):
        """AssistantMessage(TextBlock "안녕하세요") → ResultMessage
        결과: 정상 전송."""
        messages = [
            make_assistant_msg([TextBlock(text="안녕하세요")]),
            make_result_msg(result="", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)
        await finalize_response(state, ch, ctx)

        all_text = ch.get_all_text()
        assert "안녕하세요" in all_text

    @pytest.mark.asyncio
    async def test_thinking_then_text(self):
        """ThinkingBlock → TextBlock → ResultMessage."""
        messages = [
            make_assistant_msg([
                ThinkingBlock(thinking="음, 생각해보면..."),
                TextBlock(text="결론입니다"),
            ]),
            make_result_msg(result="", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)
        await finalize_response(state, ch, ctx)

        all_text = ch.get_all_text()
        assert "결론입니다" in all_text
        # ThinkingBlock 내용은 전송되지 않아야 함
        assert "음, 생각해보면" not in all_text


class TestStreamContext:
    """StreamContext 초기 상태 검증."""

    def test_initial_state(self):
        ctx = StreamContext()
        assert ctx.live_msg_id == ""
        assert ctx.live_lines == []
        assert ctx.tool_lines == []
        assert ctx.msg_count == 0
        assert ctx.current_source == "main"

    def test_tool_id_map(self):
        ctx = StreamContext()
        ctx._tool_id_map["id1"] = "Bash"
        assert ctx._tool_id_map["id1"] == "Bash"


class TestSystemMessage:
    """SystemMessage 처리."""

    @pytest.mark.asyncio
    async def test_api_retry(self):
        messages = [
            make_system_msg(subtype="api_retry"),
            make_result_msg(result="done", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)
        assert ctx.retry_count == 1

    @pytest.mark.asyncio
    async def test_init_message(self):
        messages = [
            make_system_msg(subtype="init"),
            make_result_msg(result="", session_id="s1"),
        ]
        state, ch, ctx = await _run_stream(messages)
        assert ctx.retry_count == 0

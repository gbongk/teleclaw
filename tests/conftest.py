"""pytest 설정 — 독립 실행용 스크립트 제외, 공통 fixture 정의."""
import sys
import os

# 패키지 import를 위해 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

collect_ignore = ["test_smoke.py", "test_smoke_live.py"]


# --- SDK mock 패치 (claude_agent_sdk를 실제 import하지 않도록) ---

import types

def _setup_mock_sdk():
    """claude_agent_sdk 모듈을 mock으로 교체. 테스트에서 실제 SDK 불필요."""
    from tests.mock_sdk import (
        AssistantMessage, UserMessage, ResultMessage, SystemMessage,
        RateLimitEvent, StreamEvent,
        TextBlock, ToolUseBlock, ThinkingBlock, ToolResultBlock,
    )

    mock_mod = types.ModuleType("claude_agent_sdk")
    mock_mod.AssistantMessage = AssistantMessage
    mock_mod.UserMessage = UserMessage
    mock_mod.ResultMessage = ResultMessage
    mock_mod.SystemMessage = SystemMessage
    mock_mod.RateLimitEvent = RateLimitEvent
    mock_mod.TextBlock = TextBlock
    mock_mod.ToolUseBlock = ToolUseBlock
    mock_mod.ThinkingBlock = ThinkingBlock
    mock_mod.ToolResultBlock = ToolResultBlock
    mock_mod.ClaudeSDKClient = type("ClaudeSDKClient", (), {})
    mock_mod.ClaudeAgentOptions = type("ClaudeAgentOptions", (), {})
    mock_mod.HookMatcher = type("HookMatcher", (), {})
    from tests.mock_sdk import TaskStartedMessage, TaskNotificationMessage
    mock_mod.TaskStartedMessage = TaskStartedMessage
    mock_mod.TaskProgressMessage = type("TaskProgressMessage", (), {})
    mock_mod.TaskNotificationMessage = TaskNotificationMessage

    mock_types = types.ModuleType("claude_agent_sdk.types")
    mock_types.StreamEvent = StreamEvent
    mock_mod.types = mock_types

    sys.modules["claude_agent_sdk"] = mock_mod
    sys.modules["claude_agent_sdk.types"] = mock_types


# conftest.py가 로드될 때 바로 mock SDK 설치
if "claude_agent_sdk" not in sys.modules:
    _setup_mock_sdk()

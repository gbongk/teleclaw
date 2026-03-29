"""Mock SDK 메시지 생성 헬퍼.

실제 claude_agent_sdk를 import하지 않고 동일한 구조의 메시지 객체를 생성.
테스트에서 스트림 핸들러에 주입할 메시지를 만들 때 사용.
"""


class TextBlock:
    def __init__(self, text=""):
        self.text = text
        self.type = "text"


class ToolUseBlock:
    def __init__(self, name="", input=None, id=""):
        self.name = name
        self.input = input or {}
        self.id = id or f"toolu_{name}_{id}"
        self.type = "tool_use"


class ThinkingBlock:
    def __init__(self, thinking=""):
        self.thinking = thinking
        self.type = "thinking"


class ToolResultBlock:
    def __init__(self, content="", tool_use_id=""):
        self.content = content
        self.tool_use_id = tool_use_id
        self.type = "tool_result"


class AssistantMessage:
    def __init__(self, content=None):
        self.content = content or []


class UserMessage:
    def __init__(self, content=None, tool_use_result=None):
        self.content = content or []
        self.tool_use_result = tool_use_result


class ResultMessage:
    def __init__(self, result="", session_id="", usage=None, total_cost_usd=None):
        self.result = result
        self.session_id = session_id or "test-session-001"
        self.usage = usage or {}
        self.total_cost_usd = total_cost_usd


class SystemMessage:
    def __init__(self, subtype="init"):
        self.subtype = subtype


class TaskStartedMessage:
    def __init__(self, task_id="", description="", tool_use_id=""):
        self.subtype = "task_started"
        self.task_id = task_id
        self.description = description
        self.uuid = "uuid-" + task_id
        self.session_id = "test-session"
        self.tool_use_id = tool_use_id
        self.data = {}
        self.task_type = "agent"


class TaskNotificationMessage:
    def __init__(self, task_id="", status="completed", summary="", output_file="", tool_use_id=""):
        self.subtype = "task_notification"
        self.task_id = task_id
        self.status = status
        self.output_file = output_file
        self.summary = summary
        self.uuid = "uuid-" + task_id
        self.session_id = "test-session"
        self.tool_use_id = tool_use_id
        self.data = {}
        self.usage = {}


class RateLimitEvent:
    def __init__(self, status="allowed", rate_limit_type="", resets_at=""):
        self.rate_limit_info = type("Info", (), {
            "status": status,
            "rate_limit_type": rate_limit_type,
            "resets_at": resets_at,
        })()


class StreamEvent:
    def __init__(self, event=""):
        self.event = event


# --- 팩토리 함수 ---

def make_assistant_msg(blocks=None):
    """AssistantMessage 생성. blocks: [TextBlock|ToolUseBlock|ThinkingBlock]"""
    return AssistantMessage(content=blocks or [])


def make_user_msg(tool_result="", tool_use_id="", tool_use_result=None):
    """UserMessage 생성 (ToolResultBlock 포함)."""
    blocks = []
    if tool_result or tool_use_id:
        blocks.append(ToolResultBlock(content=tool_result, tool_use_id=tool_use_id))
    return UserMessage(content=blocks, tool_use_result=tool_use_result)


def make_result_msg(result="", session_id="", usage=None):
    """ResultMessage 생성."""
    return ResultMessage(result=result, session_id=session_id, usage=usage)


def make_system_msg(subtype="init"):
    """SystemMessage 생성."""
    return SystemMessage(subtype=subtype)


async def async_message_stream(messages):
    """메시지 리스트를 async generator로 변환.

    Usage:
        async for msg in async_message_stream([msg1, msg2, msg3]):
            process(msg)
    """
    for msg in messages:
        yield msg

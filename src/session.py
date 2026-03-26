"""SessionState 데이터클래스"""

import asyncio
from dataclasses import dataclass, field

from claude_code_sdk import ClaudeSDKClient


@dataclass
class SessionState:
    name: str
    config: dict
    client: ClaudeSDKClient | None = None
    channel: "Channel | None" = None  # hub.channel.Channel
    connected: bool = False
    busy: bool = False
    message_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    error_count: int = 0
    start_time: float = 0.0
    query_count: int = 0
    restart_count: int = 0
    restart_history: list = field(default_factory=list)
    last_notify_time: float = 0.0
    restarting: bool = False
    busy_since: float = 0.0
    session_id: str | None = None
    resume_count: int = 0  # 연속 자동 재개 횟수 (정상 완료 시 리셋)
    last_restart_mode: str = ""  # 마지막 재시작 모드 (resume/reset/crash)
    was_busy_before_restart: bool = False  # 재시작 전 busy 상태였는지
    no_resume_before_restart: bool = False  # TeleClaw/flag 재시작 시 auto-resume 루프 방지

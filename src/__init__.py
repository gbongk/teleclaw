"""텔레그램 TeleClaw 패키지"""

import asyncio

from .config import PROJECTS, CHAT_ID, SUPERVISOR_DIR, LOGS_DIR
from .logging_utils import log, _find_existing_teleclaw, _write_lock, _release_lock
from .channel import Channel
from .channel_telegram import TelegramChannel
from .session import SessionState
from .teleclaw import TeleClaw, main as _async_main


def main():
    """CLI 진입점 — 서브커맨드 지원.

    teleclaw            → TeleClaw 실행
    teleclaw install    → 시스템 서비스 등록
    teleclaw uninstall  → 시스템 서비스 해제
    teleclaw status     → 서비스 상태
    teleclaw logs [N]   → 서비스 로그
    """
    import sys
    args = sys.argv[1:]
    if args:
        cmd = args[0].lower()
        from . import service
        if cmd == "install":
            service.install()
            return
        if cmd == "uninstall":
            service.uninstall()
            return
        if cmd == "status":
            service.status()
            return
        if cmd == "logs":
            n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 50
            service.logs(n)
            return
    asyncio.run(_async_main())


__all__ = [
    "TeleClaw",
    "SessionState",
    "main",
    "log",
    "Channel",
    "TelegramChannel",
    "PROJECTS",
]

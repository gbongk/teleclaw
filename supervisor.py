#!/usr/bin/env python3
"""
텔레그램 슈퍼바이저 — Claude Code SDK 기반 텔레그램 봇
텔레그램 메시지 수신 → SDK query → 응답 → 텔레그램 전송.
health check, 재시작, 상태 관리, watchdog 통합.

이 파일은 supervisor 패키지의 진입점입니다.
실제 코드는 supervisor/ 패키지 내 모듈들에 있습니다.
"""

import asyncio
from supervisor.supervisor import main

if __name__ == "__main__":
    asyncio.run(main())

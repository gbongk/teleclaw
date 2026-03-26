#!/usr/bin/env python3
"""텔레그램으로 이미지/파일 전송 CLI 래퍼.

Usage:
    python send_telegram.py photo <path> [caption]
    python send_telegram.py file  <path> [caption]
"""
import os
import sys

_SUPERVISOR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SUPERVISOR_DIR)

from hub.config import PROJECTS, CHAT_ID
from hub import telegram_api as tg


def _match_project():
    """cwd 기반으로 PROJECTS에서 bot_token 매칭."""
    cwd = os.getcwd().replace("\\", "/").rstrip("/")
    for name, cfg in PROJECTS.items():
        proj_cwd = cfg.get("cwd", "").replace("\\", "/").rstrip("/")
        if proj_cwd and (cwd == proj_cwd or cwd.startswith(proj_cwd + "/")):
            return cfg["bot_token"], name
    if PROJECTS:
        first = next(iter(PROJECTS.values()))
        return first["bot_token"], next(iter(PROJECTS.keys()))
    return None, None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: send_telegram.py <photo|file> <path> [caption]")
        sys.exit(1)

    kind = sys.argv[1]
    path = sys.argv[2]
    caption = sys.argv[3] if len(sys.argv) > 3 else ""

    if kind not in ("photo", "file"):
        print("First argument must be 'photo' or 'file'")
        sys.exit(1)
    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)

    bot_token, proj_name = _match_project()
    if not bot_token:
        print("No telegram config found")
        sys.exit(1)

    if kind == "photo":
        mid = tg.send_photo_sync(bot_token, path, caption)
    else:
        mid = tg.send_file_sync(bot_token, path, caption)

    if mid:
        print(f"Sent: {kind} {os.path.basename(path)}")
    else:
        print("Send failed", file=sys.stderr)
        sys.exit(1)

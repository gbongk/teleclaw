"""usage 포맷 유틸 — commands.py, teleclaw_ctl.py에서 공유."""

from datetime import datetime, timezone


def usage_bar(pct, emoji=True):
    """20칸 바 포맷. emoji=True면 색상 아이콘 포함."""
    filled = round(pct / 5)
    empty = 20 - filled
    bar = f"{'|' * filled}{'.' * empty} {pct:.0f}%"
    if emoji:
        if pct >= 90:
            icon = "\U0001f534"
        elif pct >= 70:
            icon = "\U0001f7e1"
        else:
            icon = "\U0001f7e2"
        return f"{icon} {bar}"
    return bar


def reset_str(bucket):
    """리셋 시간까지 남은 시간 문자열."""
    reset_at = bucket.get("resets_at", "") if bucket else ""
    if not reset_at:
        return ""
    try:
        dt = datetime.fromisoformat(reset_at)
        remaining = (dt - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return "(리셋됨)"
        rm, rs = divmod(int(remaining), 60)
        rh, rm = divmod(rm, 60)
        rd, rh = divmod(rh, 24)
        if rd > 0:
            return f"({rd}d {rh}h {rm}m)"
        if rh > 0:
            return f"({rh}h {rm}m)"
        return f"({rm}m)"
    except Exception:
        return ""

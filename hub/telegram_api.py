"""텔레그램 API 함수 + 텍스트 유틸리티"""

import re
import httpx

from .config import CHAT_ID, PROJECTS
from .logging_utils import log

# --- 텔레그램 API ---

def send_telegram(text: str, bot_token: str, bot_name: str = "", use_html: bool = False, notify: bool = False) -> int:
    """메시지 전송 후 message_id 반환 (실패 시 0). notify=True면 알림 소리 활성화."""
    if bot_name:
        prefix = f"[{bot_name}] "
        text = prefix + text
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    last_msg_id = 0
    chunks = _split_message(text)
    for chunk in chunks:
        payload = {
            "chat_id": CHAT_ID,
            "text": chunk[:4096],
            "disable_web_page_preview": True,
            "disable_notification": not notify,
        }
        if use_html:
            payload["parse_mode"] = "HTML"
        try:
            r = httpx.post(url, json=payload, timeout=15)
            data = r.json()
            if not data.get("ok") and use_html:
                # HTML 파싱 실패 시 plain text fallback
                payload.pop("parse_mode", None)
                r = httpx.post(url, json=payload, timeout=15)
                data = r.json()
            last_msg_id = data.get("result", {}).get("message_id", 0)
        except Exception as e:
            log(f"텔레그램 전송 실패: {e}")
    return last_msg_id


def edit_telegram(text: str, message_id: int, bot_token: str, bot_name: str = "") -> bool:
    """기존 메시지 수정. "message not modified" 무시."""
    if bot_name:
        text = f"[{bot_name}] {text}"
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    try:
        r = httpx.post(url, json={
            "chat_id": CHAT_ID,
            "message_id": message_id,
            "text": text[:4096],
            "disable_web_page_preview": True,
        }, timeout=15)
        if r.status_code == 200:
            return True
        # "message is not modified" — 내용 동일, 무시
        if r.status_code == 400 and "not modified" in r.text:
            return True
        log(f"edit 실패 ({r.status_code}): {r.text[:100]}")
        return False
    except Exception as e:
        log(f"edit 예외: {e}")
        return False


def send_ack(bot_token: str, msg_id: int, bot_name: str = ""):
    prefix = f"[{bot_name}] " if bot_name else ""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        httpx.post(url, json={
            "chat_id": CHAT_ID,
            "text": f"{prefix}\u2705",
            "reply_to_message_id": msg_id,
        }, timeout=5)
    except Exception:
        pass


# --- 텍스트 유틸리티 ---

_re_blank_lines = re.compile(r"\n{3,}")
_re_control_chars = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

def _clean_text(text: str) -> str:
    """제어 문자 제거 + 연속 빈 줄 정리 + 깨진 문자 치환 + URL 제거"""
    text = _re_control_chars.sub("", text)
    # cp949 깨진 문자 복구 시도
    try:
        raw = text.encode("utf-8", errors="surrogateescape")
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    # U+FFFD (replacement char) 및 연속 깨진 문자 제거
    text = re.sub(r"\ufffd+", "?", text)
    # URL 제거 — 마크다운 링크 텍스트만 유지, bare URL 제거
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = _re_blank_lines.sub("\n\n", text)
    return text.strip()


# --- 마크다운 → 텔레그램 HTML 변환 ---

def _escape_html(text: str) -> str:
    """HTML 특수문자 이스케이프 (코드블록 외부용)"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _convert_table_to_list(text: str) -> str:
    """마크다운 테이블 → 리스트 형태 변환"""
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # 테이블 헤더 감지: | col | col | + 다음 줄이 |---|---|
        if "|" in line and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
            headers = [h.strip() for h in line.split("|")[1:-1]]
            i += 2  # 헤더 + 구분선 건너뜀
            while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
                cols = [c.strip() for c in lines[i].split("|")[1:-1]]
                if len(cols) >= 2:
                    entry = f"\u25aa\ufe0f {cols[0]}: {cols[1]}"
                    if len(cols) > 2 and cols[2]:
                        entry += f" \u2014 {cols[2]}"
                    result.append(entry)
                i += 1
        else:
            result.append(lines[i])
            i += 1
    return "\n".join(result)


def _md_to_telegram_html(text: str) -> str:
    """GitHub Flavored Markdown → Telegram HTML 변환. 실패 시 plain text 반환."""
    try:
        # 테이블 변환 (HTML 이스케이프 전에 처리)
        text = _convert_table_to_list(text)

        # 코드블록 보호 (언어명 + 개행 / 언어명 없이 / 한줄 코드블록)
        code_blocks = []
        def _save_code(m):
            code_blocks.append(m.group(1))
            return f"__CODEBLOCK_{len(code_blocks) - 1}__"
        # 언어명 뒤 개행이 있는 경우 먼저 매치
        text = re.sub(r"```\w*\n(.*?)```", _save_code, text, flags=re.DOTALL)
        # 남은 코드블록 (한줄, 언어명 없음)
        text = re.sub(r"```(.*?)```", _save_code, text, flags=re.DOTALL)

        # 인라인 코드 보호
        inline_codes = []
        def _save_inline(m):
            inline_codes.append(m.group(1))
            return f"__INLINE_{len(inline_codes) - 1}__"
        text = re.sub(r"`([^`]+)`", _save_inline, text)

        # HTML 이스케이프 (코드블록/인라인 보호 후)
        text = _escape_html(text)

        # 볼드+이탤릭 (***text***)
        text = re.sub(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*", r"<b><i>\1</i></b>", text)
        # 볼드 (**text**)
        text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", text)
        # 이탤릭 (*text*) — 볼드 처리 후 남은 단독 *만
        text = re.sub(r"(?<!\*)\*(?=\S)([^*]+?)(?<=\S)\*(?!\*)", r"<i>\1</i>", text)
        # 취소선
        text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
        # 헤더 → 볼드
        text = re.sub(r"^#{1,3}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

        # 인용 → <blockquote> (텔레그램 공식 지원)
        # 연속 인용줄을 하나의 blockquote로 묶기
        def _merge_blockquotes(text):
            lines = text.split("\n")
            result = []
            in_quote = False
            for line in lines:
                is_quote = line.startswith("&gt;")
                if is_quote:
                    content = re.sub(r"^&gt;\s?", "", line)
                    if not in_quote:
                        result.append(f"<blockquote>{content}")
                        in_quote = True
                    else:
                        result.append(content)
                else:
                    if in_quote:
                        result[-1] += "</blockquote>"
                        in_quote = False
                    result.append(line)
            if in_quote:
                result[-1] += "</blockquote>"
            return "\n".join(result)
        text = _merge_blockquotes(text)

        # 링크 [text](url) → text만 남기기 (텔레그램에서 URL 미리보기 방지)
        text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"\1", text)
        # 나머지 bare URL 제거 (코드블록 밖)
        text = re.sub(r"https?://\S+", "", text)

        # 도구 라인 → <code> 태그 (구분감 부여)
        text = re.sub(r"^(\u2500 \U0001f527 .+)$", r"<code>\1</code>", text, flags=re.MULTILINE)

        # 연속 빈 줄 정리 (3줄+ → 2줄)
        text = re.sub(r"\n{3,}", "\n\n", text)

        # 인라인 코드 복원
        for i, code in enumerate(inline_codes):
            text = text.replace(f"__INLINE_{i}__", f"<code>{_escape_html(code)}</code>")

        # 코드블록 복원
        for i, code in enumerate(code_blocks):
            text = text.replace(f"__CODEBLOCK_{i}__", f"<pre>{_escape_html(code)}</pre>")

        return text
    except Exception as e:
        log(f"HTML 변환 실패: {e}")
        return _escape_html(text)


def _split_message(text: str, max_len: int = 4000) -> list:
    """의미 단위로 메시지 분할 (빈줄 > 줄바꿈 > 공백 우선)"""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # 분할 지점 탐색: 빈줄 > 줄바꿈 > 공백
        cut = text.rfind("\n\n", 0, max_len)
        if cut < max_len // 2:
            cut = text.rfind("\n", 0, max_len)
        if cut < max_len // 2:
            cut = text.rfind(" ", 0, max_len)
        if cut < 0:
            cut = max_len

        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")

    if len(chunks) > 1:
        chunks = [f"{c}\n\n({i + 1}/{len(chunks)})" for i, c in enumerate(chunks)]

    return chunks


# --- 비동기 텔레그램 API (세션 루프용) ---

async def async_send_telegram(ahttp: httpx.AsyncClient, text: str, bot_token: str, bot_name: str = "", use_html: bool = False, reply_to: int = 0) -> int:
    text = _clean_text(text)
    if bot_name:
        text = f"[{bot_name}] {text}"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        payload = {
            "chat_id": CHAT_ID,
            "text": text[:4096],
            "disable_web_page_preview": True,
            "disable_notification": True,
        }
        if reply_to:
            payload["reply_parameters"] = {"message_id": reply_to}
        if use_html:
            payload["parse_mode"] = "HTML"
        r = await ahttp.post(url, json=payload, timeout=15)
        data = r.json()
        if not data.get("ok") and use_html:
            payload.pop("parse_mode", None)
            r = await ahttp.post(url, json=payload, timeout=15)
            data = r.json()
        return data.get("result", {}).get("message_id", 0)
    except Exception as e:
        log(f"텔레그램 전송 실패: {e}")
        return 0


async def async_edit_telegram(ahttp: httpx.AsyncClient, text: str, message_id: int, bot_token: str, bot_name: str = "", use_html: bool = False) -> bool:
    text = _clean_text(text)
    if bot_name:
        text = f"[{bot_name}] {text}"
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    try:
        payload = {
            "chat_id": CHAT_ID,
            "message_id": message_id,
            "text": text[:4096],
            "disable_web_page_preview": True,
        }
        if use_html:
            payload["parse_mode"] = "HTML"
        r = await ahttp.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            return True
        if r.status_code == 400 and "not modified" in r.text:
            return True
        # HTML 파싱 실패 시 plain text fallback
        if r.status_code == 400 and use_html:
            payload.pop("parse_mode", None)
            r = await ahttp.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                return True
        log(f"edit 실패 ({r.status_code}): {r.text[:100]}")
        return False
    except Exception as e:
        log(f"edit 예외: {e}")
        return False


async def async_react(ahttp: httpx.AsyncClient, bot_token: str, msg_id: int, emoji: str = "\U0001f440"):
    """사용자 메시지에 리액션 추가 (알림 없이 수신 확인)."""
    url = f"https://api.telegram.org/bot{bot_token}/setMessageReaction"
    try:
        await ahttp.post(url, json={
            "chat_id": CHAT_ID,
            "message_id": msg_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
        }, timeout=5)
    except Exception:
        pass


def _notify_all(text: str):
    """전체 알림 — 모든 봇에 broadcast (동기)"""
    sent = set()
    for name, config in PROJECTS.items():
        token = config.get("bot_token", "")
        if token and token not in sent:
            send_telegram(text, token)
            sent.add(token)


async def async_notify_all(ahttp, text: str):
    """전체 알림 — 모든 봇에 broadcast (비동기, asyncio 루프 blocking 방지)"""
    sent = set()
    for name, config in PROJECTS.items():
        token = config.get("bot_token", "")
        if token and token not in sent:
            await async_send_telegram(ahttp, text, token)
            sent.add(token)

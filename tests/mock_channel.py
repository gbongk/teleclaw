"""Mock 텔레그램 채널.

Channel 인터페이스를 구현하며, 전송된 메시지를 기록하여 테스트에서 검증 가능.
"""

import uuid


class MockChannel:
    """테스트용 채널. 모든 전송을 sent_messages에 기록."""

    def __init__(self):
        self.sent_messages: list[dict] = []
        self.edited_messages: list[dict] = []
        self.deleted_messages: list[str] = []
        self._msg_counter = 0

    @property
    def name(self) -> str:
        return "mock"

    @property
    def max_length(self) -> int:
        return 4096

    def _next_id(self) -> str:
        self._msg_counter += 1
        return str(self._msg_counter)

    async def send(self, text: str, reply_to: str = "", use_markup: bool = False) -> str:
        msg_id = self._next_id()
        self.sent_messages.append({
            "id": msg_id,
            "text": text,
            "reply_to": reply_to,
            "use_markup": use_markup,
        })
        return msg_id

    async def edit(self, message_id: str, text: str, use_markup: bool = False) -> bool:
        self.edited_messages.append({
            "id": message_id,
            "text": text,
            "use_markup": use_markup,
        })
        return True

    async def delete(self, message_id: str) -> bool:
        self.deleted_messages.append(message_id)
        return True

    async def react(self, message_id: str, emoji: str = "") -> bool:
        return True

    def send_sync(self, text: str, use_markup: bool = False, notify: bool = False) -> str:
        msg_id = self._next_id()
        self.sent_messages.append({
            "id": msg_id,
            "text": text,
            "use_markup": use_markup,
            "sync": True,
        })
        return msg_id

    async def send_photo(self, file_path: str, caption: str = "") -> str:
        return self._next_id()

    async def send_file(self, file_path: str, caption: str = "") -> str:
        return self._next_id()

    async def poll(self, timeout: int = 25) -> list:
        return []

    def format(self, markdown_text: str) -> str:
        """마크다운 변환 없이 그대로 반환 (테스트 단순화)."""
        return markdown_text

    def split(self, text: str) -> list:
        """4096자 기준 분할."""
        if len(text) <= self.max_length:
            return [text]
        chunks = []
        while text:
            if len(text) <= self.max_length:
                chunks.append(text)
                break
            cut = text.rfind("\n", 0, self.max_length)
            if cut < self.max_length // 2:
                cut = self.max_length
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        return chunks

    # --- assert 헬퍼 ---

    def assert_sent(self, text_fragment: str, msg=""):
        """전송된 메시지 중 text_fragment를 포함하는 것이 있는지 확인."""
        for m in self.sent_messages:
            if text_fragment in m["text"]:
                return m
        all_texts = [m["text"][:100] for m in self.sent_messages]
        raise AssertionError(
            msg or f"'{text_fragment}' not found in sent messages. "
                   f"Sent ({len(self.sent_messages)}): {all_texts}"
        )

    def assert_not_sent(self, text_fragment: str, msg=""):
        """전송된 메시지 중 text_fragment를 포함하는 것이 없는지 확인."""
        for m in self.sent_messages:
            if text_fragment in m["text"]:
                raise AssertionError(
                    msg or f"'{text_fragment}' unexpectedly found in: {m['text'][:200]}"
                )

    def assert_sent_count(self, n: int, msg=""):
        """전송된 메시지 수가 정확히 n인지 확인."""
        actual = len(self.sent_messages)
        if actual != n:
            texts = [m["text"][:80] for m in self.sent_messages]
            raise AssertionError(
                msg or f"Expected {n} sent messages, got {actual}: {texts}"
            )

    def get_all_text(self) -> str:
        """전송된 모든 메시지 텍스트를 합쳐 반환."""
        return "\n".join(m["text"] for m in self.sent_messages)

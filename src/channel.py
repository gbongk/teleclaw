"""채널 추상 인터페이스 — 텔레그램, Discord 등 메시징 플랫폼 공통 API.

사용법:
    channel = TelegramChannel(bot_token, chat_id)
    msg_id = await channel.send("Hello")
    await channel.edit(msg_id, "Hello, updated")
"""

from abc import ABC, abstractmethod


class Channel(ABC):
    """메시지 수신/전송 추상 인터페이스."""

    @property
    @abstractmethod
    def name(self) -> str:
        """채널 이름 (예: "telegram", "discord")"""

    @property
    @abstractmethod
    def max_length(self) -> int:
        """메시지 최대 길이 (텔레그램: 4096, Discord: 2000)"""

    # --- 수신 ---

    @abstractmethod
    async def poll(self, timeout: int = 25) -> list:
        """새 메시지 폴링.
        Returns: [{"id": str, "text": str, "from_id": str, "reply_to": str|None, "files": [...]}]
        """

    # --- 전송 ---

    @abstractmethod
    async def send(self, text: str, reply_to: str = "", use_markup: bool = False) -> str:
        """메시지 전송. Returns: message_id (str)"""

    @abstractmethod
    async def edit(self, message_id: str, text: str, use_markup: bool = False) -> bool:
        """메시지 편집."""

    @abstractmethod
    async def delete(self, message_id: str) -> bool:
        """메시지 삭제."""

    @abstractmethod
    async def react(self, message_id: str, emoji: str = "") -> bool:
        """리액션/이모지 추가."""

    # --- 전송 (동기, 명령어 응답용) ---

    @abstractmethod
    def send_sync(self, text: str, use_markup: bool = False, notify: bool = False) -> str:
        """동기 메시지 전송. commands.py 등에서 사용."""

    # --- 파일 전송 ---

    @abstractmethod
    async def send_photo(self, file_path: str, caption: str = "") -> str:
        """이미지 전송. Returns: message_id (str)"""

    @abstractmethod
    async def send_file(self, file_path: str, caption: str = "") -> str:
        """파일 전송. Returns: message_id (str)"""

    def send_photo_sync(self, file_path: str, caption: str = "") -> str:
        """동기 이미지 전송. CLI/훅용."""
        return ""

    def send_file_sync(self, file_path: str, caption: str = "") -> str:
        """동기 파일 전송. CLI/훅용."""
        return ""

    # --- 파일 다운로드 ---

    async def download_file(self, file_ref: str) -> bytes:
        """파일 다운로드. file_ref는 플랫폼별 (텔레그램: file_id)."""
        return b""

    # --- 포맷팅 ---

    def format(self, markdown_text: str) -> str:
        """마크다운 → 플랫폼 네이티브 포맷 변환.
        기본: 그대로 반환. 텔레그램은 HTML로 변환."""
        return markdown_text

    def split(self, text: str) -> list:
        """플랫폼 제한에 맞춰 메시지 분할.
        기본: max_length 기준 단순 분할."""
        if len(text) <= self.max_length:
            return [text]
        chunks = []
        while text:
            if len(text) <= self.max_length:
                chunks.append(text)
                break
            # 줄바꿈 기준 분할
            cut = text.rfind("\n", 0, self.max_length)
            if cut < self.max_length // 2:
                cut = self.max_length
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        return chunks

    # --- 브로드캐스트 (여러 봇에 알림) ---

    def broadcast_sync(self, text: str):
        """전체 채널에 동기 알림. 기본: send_sync."""
        self.send_sync(text)

    async def broadcast(self, text: str):
        """전체 채널에 비동기 알림. 기본: send."""
        await self.send(text)

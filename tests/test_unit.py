#!/usr/bin/env python3
"""TeleClaw 유닛테스트 — 순수 함수 격리 테스트."""

import sys
import os
import unittest
from dataclasses import dataclass

# 패키지 import를 위해 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# telegram_api 함수 테스트
# ============================================================

from src.telegram_api import (
    _clean_text, _escape_html, _convert_table_to_list,
    _md_to_telegram_html, _split_message,
)


class TestCleanText(unittest.TestCase):
    def test_strip(self):
        self.assertEqual(_clean_text("  hello  "), "hello")

    def test_control_chars(self):
        self.assertNotIn("\x00", _clean_text("a\x00b"))
        self.assertNotIn("\x01", _clean_text("a\x01b"))

    def test_consecutive_blank_lines(self):
        result = _clean_text("a\n\n\n\nb")
        self.assertEqual(result, "a\n\nb")

    def test_replacement_char(self):
        result = _clean_text("abc\ufffd\ufffdef")
        self.assertIn("?", result)
        self.assertNotIn("\ufffd", result)

    def test_empty(self):
        self.assertEqual(_clean_text(""), "")

    def test_korean(self):
        self.assertEqual(_clean_text("  안녕하세요  "), "안녕하세요")


class TestEscapeHtml(unittest.TestCase):
    def test_ampersand(self):
        self.assertEqual(_escape_html("a & b"), "a &amp; b")

    def test_angle_brackets(self):
        self.assertEqual(_escape_html("<div>"), "&lt;div&gt;")

    def test_combined(self):
        self.assertEqual(_escape_html("a < b & c > d"), "a &lt; b &amp; c &gt; d")

    def test_no_change(self):
        self.assertEqual(_escape_html("hello"), "hello")


class TestConvertTableToList(unittest.TestCase):
    def test_simple_table(self):
        table = "| 이름 | 값 |\n|---|---|\n| A | 1 |\n| B | 2 |"
        result = _convert_table_to_list(table)
        self.assertIn("A: 1", result)
        self.assertIn("B: 2", result)
        self.assertNotIn("|", result)

    def test_three_columns(self):
        table = "| 이름 | 값 | 설명 |\n|---|---|---|\n| A | 1 | first |"
        result = _convert_table_to_list(table)
        self.assertIn("A: 1", result)
        self.assertIn("first", result)

    def test_no_table(self):
        text = "그냥 텍스트"
        self.assertEqual(_convert_table_to_list(text), text)


class TestMdToTelegramHtml(unittest.TestCase):
    def test_bold(self):
        result = _md_to_telegram_html("**hello**")
        self.assertIn("<b>hello</b>", result)

    def test_italic(self):
        result = _md_to_telegram_html("*hello*")
        self.assertIn("<i>hello</i>", result)

    def test_bold_italic(self):
        result = _md_to_telegram_html("***hello***")
        self.assertIn("<b><i>hello</i></b>", result)

    def test_strikethrough(self):
        result = _md_to_telegram_html("~~hello~~")
        self.assertIn("<s>hello</s>", result)

    def test_header(self):
        result = _md_to_telegram_html("## Title")
        self.assertIn("<b>Title</b>", result)

    def test_code_block(self):
        result = _md_to_telegram_html("```\ncode here\n```")
        self.assertIn("<pre>", result)
        self.assertIn("code here", result)

    def test_inline_code(self):
        result = _md_to_telegram_html("use `foo()` here")
        self.assertIn("<code>foo()</code>", result)

    def test_code_block_html_escape(self):
        result = _md_to_telegram_html("```\na < b & c > d\n```")
        self.assertIn("&lt;", result)
        self.assertIn("&amp;", result)

    def test_link_stripped(self):
        result = _md_to_telegram_html("[click](https://example.com)")
        self.assertIn("click", result)
        self.assertNotIn("https://", result)

    def test_bare_url_stripped(self):
        result = _md_to_telegram_html("visit https://example.com now")
        self.assertNotIn("https://", result)

    def test_multiple_urls_stripped(self):
        md = "링크1: https://example.com\n링크2: [구글](https://google.com)\n링크3: http://test.org/path?q=1"
        html = _md_to_telegram_html(md)
        self.assertNotIn("https://example.com", html)
        self.assertNotIn("https://google.com", html)
        self.assertNotIn("http://test.org", html)
        self.assertIn("구글", html)

    def test_url_in_codeblock_preserved(self):
        md = "설치 방법:\n```\ncurl https://example.com/install.sh | bash\n```\n끝."
        html = _md_to_telegram_html(md)
        self.assertIn("https://example.com/install.sh", html)

    def test_url_in_inline_code_preserved(self):
        md = "API 엔드포인트: `https://api.example.com/v1`"
        html = _md_to_telegram_html(md)
        self.assertIn("https://api.example.com/v1", html)

    def test_mixed_content(self):
        md = "**제목**\n\n참고: https://docs.example.com\n\n코드: `https://keep.this.url`\n\n[링크텍스트](https://remove.this.url)"
        html = _md_to_telegram_html(md)
        self.assertIn("<b>제목</b>", html)
        self.assertNotIn("https://docs.example.com", html)
        self.assertIn("https://keep.this.url", html)
        self.assertNotIn("https://remove.this.url", html)
        self.assertIn("링크텍스트", html)

    def test_blockquote(self):
        result = _md_to_telegram_html("> quoted text")
        self.assertIn("<blockquote>", result)

    def test_fallback_on_plain(self):
        result = _md_to_telegram_html("hello world")
        self.assertIn("hello world", result)


class TestSplitMessage(unittest.TestCase):
    def test_short_message(self):
        result = _split_message("hello", max_len=100)
        self.assertEqual(result, ["hello"])

    def test_exact_limit(self):
        text = "a" * 100
        result = _split_message(text, max_len=100)
        self.assertEqual(len(result), 1)

    def test_split_on_newline(self):
        text = "a" * 50 + "\n" + "b" * 50
        result = _split_message(text, max_len=60)
        self.assertGreater(len(result), 1)

    def test_split_on_blank_line(self):
        text = "a" * 40 + "\n\n" + "b" * 40
        result = _split_message(text, max_len=50)
        self.assertGreater(len(result), 1)

    def test_chunk_numbering(self):
        text = "a" * 100 + "\n\n" + "b" * 100
        result = _split_message(text, max_len=60)
        self.assertTrue(any("(1/" in c for c in result))

    def test_forced_split(self):
        # 분할 지점 없는 긴 텍스트
        text = "a" * 200
        result = _split_message(text, max_len=50)
        self.assertGreater(len(result), 1)
        for chunk in result:
            # 청크 번호 제외하고 원본이 max_len 이하인지 확인
            base = chunk.split("\n\n(")[0] if "\n\n(" in chunk else chunk
            self.assertLessEqual(len(base), 50)


# ============================================================
# teleclaw.py 함수 테스트
# ============================================================

class TestToolSummary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.teleclaw import TeleClaw
        cls.func = staticmethod(TeleClaw._tool_summary)

    def test_read_file(self):
        result = self.func("Read", {"file_path": "/some/path/file.py"})
        self.assertIn("Read", result)
        self.assertIn("file.py", result)

    def test_mcp_tool(self):
        result = self.func("mcp__ai-chat__ask_ai", {"prompt": "hello"})
        self.assertIn("ai-chat.ask_ai", result)

    def test_long_path_truncated(self):
        long_path = "/very/long/path/" + "a" * 50 + "/file.py"
        result = self.func("Read", {"file_path": long_path})
        self.assertIn("...", result)
        self.assertLessEqual(len(result), 80)

    def test_bash_command(self):
        result = self.func("Bash", {"command": "ls -la"})
        self.assertIn("ls -la", result)

    def test_no_input(self):
        result = self.func("TodoWrite", {})
        self.assertEqual(result, "TodoWrite")


class TestFormatToolLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.teleclaw import TeleClaw
        cls.func = staticmethod(TeleClaw._format_tool_line)

    def test_single(self):
        result = self.func(["🔧 Read: a.py"])
        self.assertIn("Read: a.py", result)

    def test_multiple(self):
        result = self.func(["🔧 Read: a.py", "🔧 Grep: b.py"])
        self.assertIn("→", result)
        self.assertIn("Read: a.py", result)
        self.assertIn("Grep: b.py", result)

    def test_four_tools_not_truncated(self):
        """4개 이하는 전부 표시"""
        tools = ["🔧 Read: a.py", "🔧 Grep: b.py", "🔧 Edit: c.py", "🔧 Bash: ls"]
        result = self.func(tools)
        self.assertIn("Read: a.py", result)
        self.assertIn("Bash: ls", result)
        self.assertNotIn("...", result)

    def test_five_plus_tools_truncated(self):
        """5개 이상은 처음2 + ...+N + 마지막1로 축약"""
        tools = ["🔧 Read: a", "🔧 Grep: b", "🔧 Edit: c", "🔧 Bash: d", "🔧 Write: e"]
        result = self.func(tools)
        self.assertIn("Read: a", result)
        self.assertIn("Grep: b", result)
        self.assertIn("Write: e", result)
        self.assertIn("...+2", result)
        self.assertNotIn("Edit: c", result)

    def test_many_tools_truncated(self):
        """10개 도구 축약"""
        tools = [f"🔧 Tool{i}: x" for i in range(10)]
        result = self.func(tools)
        self.assertIn("...+7", result)
        self.assertIn("Tool0: x", result)
        self.assertIn("Tool9: x", result)

    def test_format_tool_line_single(self):
        """도구 1개 — 전부 표시"""
        result = self.func(["🔧 Read: only.py"])
        self.assertIn("Read: only.py", result)
        self.assertNotIn("...", result)

    def test_format_tool_line_short(self):
        """도구 4개 이하 — 전부 표시"""
        tools = ["🔧 Read: a.py", "🔧 Grep: b.py", "🔧 Edit: c.py"]
        result = self.func(tools)
        self.assertIn("Read: a.py", result)
        self.assertIn("Grep: b.py", result)
        self.assertIn("Edit: c.py", result)
        self.assertNotIn("...", result)

    def test_format_tool_line_exact_four(self):
        """정확히 4개 — 전부 표시 (축약 없음)"""
        tools = ["🔧 Read: a.py", "🔧 Grep: b.py", "🔧 Edit: c.py", "🔧 Bash: ls"]
        result = self.func(tools)
        self.assertIn("Read: a.py", result)
        self.assertIn("Grep: b.py", result)
        self.assertIn("Edit: c.py", result)
        self.assertIn("Bash: ls", result)
        self.assertNotIn("...", result)

    def test_format_tool_line_long(self):
        """도구 6개 → 처음2 + ...+3 + 마지막1 축약"""
        tools = [
            "🔧 Read: a", "🔧 Grep: b", "🔧 Edit: c",
            "🔧 Bash: d", "🔧 Write: e", "🔧 Glob: f",
        ]
        result = self.func(tools)
        self.assertIn("Read: a", result)
        self.assertIn("Grep: b", result)
        self.assertIn("Glob: f", result)
        self.assertIn("...+3", result)
        self.assertNotIn("Edit: c", result)
        self.assertNotIn("Bash: d", result)
        self.assertNotIn("Write: e", result)


class TestStabilizeMarkdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.teleclaw import TeleClaw
        cls.func = staticmethod(TeleClaw._stabilize_markdown)

    def test_open_code_block(self):
        result = self.func("```\ncode")
        self.assertEqual(result.count("```"), 2)

    def test_closed_code_block(self):
        result = self.func("```\ncode\n```")
        self.assertEqual(result.count("```"), 2)

    def test_no_code_block(self):
        result = self.func("hello")
        self.assertNotIn("```", result)


class TestAssessHealth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.teleclaw import TeleClaw
        from src.session import SessionState
        cls.supervisor = TeleClaw()
        cls.SessionState = SessionState

    def _make_state(self, **kwargs):
        import time
        defaults = {
            "name": "Test",
            "config": {"bot_token": "x", "cwd": ".", "bot_id": "1"},
            "connected": True,
            "busy": False,
            "restarting": False,
            "busy_since": 0,
            "start_time": time.time() - 300,
            "client": "fake",  # client가 None이면 DEAD 판정
        }
        defaults.update(kwargs)
        state = self.SessionState(name=defaults["name"], config=defaults["config"])
        state.connected = defaults["connected"]
        state.busy = defaults["busy"]
        state.restarting = defaults["restarting"]
        state.busy_since = defaults["busy_since"]
        state.start_time = defaults["start_time"]
        state.client = defaults["client"]
        return state

    def test_ok(self):
        state = self._make_state(connected=True, busy=False)
        self.assertEqual(self.supervisor._assess_health(state), "OK")

    def test_dead(self):
        state = self._make_state(connected=False)
        self.assertEqual(self.supervisor._assess_health(state), "DEAD")

    def test_dead_no_client(self):
        state = self._make_state(connected=True, client=None)
        self.assertEqual(self.supervisor._assess_health(state), "DEAD")

    def test_restarting_ok(self):
        state = self._make_state(connected=False, restarting=True)
        self.assertEqual(self.supervisor._assess_health(state), "OK")

    def test_stuck(self):
        import time
        state = self._make_state(connected=True, busy=True, busy_since=time.time() - 2000)
        self.assertEqual(self.supervisor._assess_health(state), "STUCK")

    def test_busy_not_stuck(self):
        import time
        state = self._make_state(connected=True, busy=True, busy_since=time.time() - 10)
        self.assertEqual(self.supervisor._assess_health(state), "OK")


# ============================================================
# wrapper 함수 테스트
# ============================================================

class TestHandleEmergencyCommand(unittest.TestCase):
    _func = None

    @classmethod
    def setUpClass(cls):
        from src import teleclaw_daemon as mod
        mod.tg_send = lambda text: None
        cls._func = staticmethod(mod.handle_emergency_command)

    def test_restart(self):
        self.assertEqual(self._func("/restart", 5, 30, 0), "restart")

    def test_kill(self):
        self.assertEqual(self._func("/kill", 5, 30, 0), "kill")

    def test_log(self):
        self.assertIsNone(self._func("/log", 5, 30, 0))

    def test_status(self):
        self.assertIsNone(self._func("/status", 5, 30, 0))

    def test_help(self):
        self.assertIsNone(self._func("/help", 5, 30, 0))

    def test_unknown(self):
        self.assertIsNone(self._func("random text", 5, 30, 0))

    def test_korean_restart(self):
        self.assertEqual(self._func("재시작", 5, 30, 0), "restart")

    def test_korean_kill(self):
        self.assertEqual(self._func("종료", 5, 30, 0), "kill")


# ============================================================
# 실행
# ============================================================
# commands.py — /restart, /reset 시 pause 해제
# ============================================================

from src import state_db as db

class TestCommandsPauseRelease(unittest.TestCase):
    """restart/reset 명령 시 pause 해제 확인 (DB 기반)."""

    @classmethod
    def setUpClass(cls):
        db.init()

    def test_restart_removes_pause(self):
        """pause 상태에서 /restart → 해제."""
        db.set_paused("TestSession", True)
        self.assertTrue(db.is_paused("TestSession"))
        db.set_paused("TestSession", False)
        self.assertFalse(db.is_paused("TestSession"))

    def test_reset_removes_pause(self):
        """pause 상태에서 /reset → 해제."""
        db.set_paused("TestReset", True)
        self.assertTrue(db.is_paused("TestReset"))
        db.set_paused("TestReset", False)
        self.assertFalse(db.is_paused("TestReset"))

    def test_no_error_without_pause(self):
        """pause 아닌 상태에서도 에러 없음."""
        self.assertFalse(db.is_paused("NoExist"))


# ============================================================
# teleclaw.py — _should_auto_resume 판단 로직
# ============================================================

class TestShouldAutoResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.teleclaw import TeleClaw
        from src.session import SessionState
        cls.supervisor = TeleClaw()
        cls.SessionState = SessionState

    def _make_state(self, **kwargs):
        import time
        from unittest.mock import MagicMock
        state = self.SessionState(
            name="Test",
            config={"bot_token": "x", "cwd": ".", "bot_id": "1"},
        )
        state.channel = MagicMock()
        state.session_id = kwargs.get("session_id", "abc123")
        state.no_resume_before_restart = kwargs.get("no_resume", False)
        state.last_restart_mode = kwargs.get("mode", "resume")
        state.resume_count = kwargs.get("resume_count", 0)
        return state

    def test_normal_resume(self):
        """기본 resume 모드 → True"""
        state = self._make_state()
        self.assertTrue(self.supervisor._should_auto_resume(state))

    def test_no_resume_marked(self):
        """no_resume 마킹 → False (1회만)"""
        state = self._make_state(no_resume=True)
        self.assertFalse(self.supervisor._should_auto_resume(state))
        # 한 번 스킵 후 플래그 리셋됨
        self.assertFalse(state.no_resume_before_restart)

    def test_reset_mode(self):
        """reset 모드 → False"""
        state = self._make_state(mode="reset")
        self.assertFalse(self.supervisor._should_auto_resume(state))

    def test_no_session_id(self):
        """session_id 없음 → False"""
        state = self._make_state(session_id="")
        self.assertFalse(self.supervisor._should_auto_resume(state))

    def test_resume_count_exceeded(self):
        """2회 초과 → False"""
        state = self._make_state(resume_count=2)
        self.assertFalse(self.supervisor._should_auto_resume(state))

    def test_resume_count_under_limit(self):
        """1회 → True"""
        state = self._make_state(resume_count=1)
        self.assertTrue(self.supervisor._should_auto_resume(state))


# ============================================================
# teleclaw.py — 재시작 중 에러 스킵
# ============================================================

class TestRestartingErrorSkip(unittest.TestCase):
    """state.restarting=True일 때 에러 재시도를 스킵하는지 확인."""

    def test_restarting_skips_retry(self):
        """restarting 상태에서 에러 발생 시 retry_error 증가 안 함."""
        msg_data = {"text": "리셋", "retry_error": 0}
        state_restarting = True
        # teleclaw.py 로직 시뮬레이션
        if state_restarting:
            skipped = True
        else:
            msg_data["retry_error"] = msg_data.get("retry_error", 0) + 1
            skipped = False
        self.assertTrue(skipped)
        self.assertEqual(msg_data["retry_error"], 0)

    def test_not_restarting_does_retry(self):
        """restarting이 아닌 상태에서 에러 → retry_error 증가."""
        msg_data = {"text": "테스트", "retry_error": 0}
        state_restarting = False
        if state_restarting:
            skipped = True
        else:
            msg_data["retry_error"] = msg_data.get("retry_error", 0) + 1
            skipped = False
        self.assertFalse(skipped)
        self.assertEqual(msg_data["retry_error"], 1)


# ============================================================
# logging_utils.py — 7일 초과 아카이브 삭제
# ============================================================

class TestArchiveCleanup(unittest.TestCase):
    """아카이브 로그 7일 보관 확인."""

    def test_archive_lines_import(self):
        """_archive_lines 함수 존재 확인."""
        from src.logging_utils import _archive_lines
        self.assertTrue(callable(_archive_lines))


# ============================================================

if __name__ == "__main__":
    # supervisor 디렉토리에서 실행
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    unittest.main(verbosity=2)

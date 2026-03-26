"""telegram_api.py 유닛 테스트 — HTML 변환, URL 제거, 테이블 변환, 메시지 분할."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.telegram_api import (
    _clean_text, _escape_html, _convert_table_to_list,
    _md_to_telegram_html, _split_message,
)


# ---------------------------------------------------------------------------
# _clean_text
# ---------------------------------------------------------------------------

def test_clean_text_control_chars():
    """제어 문자 제거"""
    assert _clean_text("hello\x00world") == "helloworld"
    assert _clean_text("test\x07\x08text") == "testtext"


def test_clean_text_blank_lines():
    """연속 빈 줄 → 2줄로"""
    assert _clean_text("a\n\n\n\nb") == "a\n\nb"


def test_clean_text_replacement_char():
    """U+FFFD → ?"""
    assert "?" in _clean_text("깨진\ufffd문자")


def test_clean_text_bare_url():
    """bare HTTP/HTTPS URL 제거"""
    assert "https://" not in _clean_text("오류: https://admob.googleapis.com/v1/accounts 발생")
    assert "http://" not in _clean_text("참고: http://old-site.com/page 입니다")
    assert "오류:" in _clean_text("오류: https://admob.googleapis.com/v1/accounts 발생")


def test_clean_text_admob_error():
    """실제 AdMob API 에러 메시지에서 URL 제거"""
    text = ('오류: <HttpError 400 when requesting '
            'https://admob.googleapis.com/v1/accounts/pub-2452567123791504/'
            'networkReport:generate?alt=json returned "Request contains an '
            'invalid argument.">')
    result = _clean_text(text)
    assert "https://" not in result
    assert "오류" in result
    assert "invalid argument" in result


def test_clean_text_markdown_link():
    """마크다운 링크 → 텍스트만 유지"""
    assert "구글" in _clean_text("[구글](https://google.com)은 검색엔진")
    assert "https://" not in _clean_text("[구글](https://google.com)은 검색엔진")


def test_clean_text_multiple_urls():
    """여러 URL 전부 제거"""
    text = "참고: https://a.com 그리고 https://b.com/path?q=1 참조"
    result = _clean_text(text)
    assert "https://" not in result
    assert "참고:" in result
    assert "참조" in result


def test_clean_text_url_only():
    """URL만 있는 텍스트 → 빈 문자열"""
    assert _clean_text("https://example.com/very/long/path") == ""


def test_clean_text_android_doc_url():
    """Android 개발 문서 URL 제거"""
    text = "자세한 내용: https://developer.android.com/topic/performance/anrs/diagnose-and-fix-anrs#nativepollonce"
    result = _clean_text(text)
    assert "https://" not in result
    assert "자세한 내용:" in result


def test_clean_text_mixed_code_and_url():
    """코드 + URL 혼합"""
    text = """크래시:
android.view.ViewRootImpl$CalledFromWrongThreadException
참고: https://developer.android.com/guide
위치: NemoActivity.java:123"""
    result = _clean_text(text)
    assert "https://" not in result
    assert "CalledFromWrongThreadException" in result
    assert "NemoActivity.java:123" in result


def test_clean_text_no_url():
    """URL 없는 텍스트는 그대로"""
    assert _clean_text("일반 텍스트입니다.") == "일반 텍스트입니다."


# ---------------------------------------------------------------------------
# _escape_html
# ---------------------------------------------------------------------------

def test_escape_html():
    assert _escape_html("<b>test</b>") == "&lt;b&gt;test&lt;/b&gt;"
    assert _escape_html("a & b") == "a &amp; b"
    assert _escape_html("normal") == "normal"


# ---------------------------------------------------------------------------
# _convert_table_to_list
# ---------------------------------------------------------------------------

def test_table_to_list():
    table = "| Name | Value |\n|---|---|\n| A | 1 |\n| B | 2 |"
    result = _convert_table_to_list(table)
    assert "A: 1" in result
    assert "B: 2" in result
    assert "|" not in result


def test_table_three_cols():
    table = "| Name | Value | Note |\n|---|---|---|\n| A | 1 | good |"
    result = _convert_table_to_list(table)
    assert "A: 1" in result
    assert "good" in result


def test_no_table():
    text = "just normal text\nno tables here"
    assert _convert_table_to_list(text) == text


# ---------------------------------------------------------------------------
# _md_to_telegram_html — URL 제거
# ---------------------------------------------------------------------------

def test_html_url_removed():
    """bare URL이 제거되는지 확인"""
    text = "참고: https://example.com/path?q=1 여기를 보세요"
    result = _md_to_telegram_html(text)
    assert "https://" not in result
    assert "example.com" not in result


def test_html_link_text_kept():
    """[text](url) → text만 남김"""
    text = "[구글](https://google.com)에서 검색"
    result = _md_to_telegram_html(text)
    assert "구글" in result
    assert "https://" not in result


def test_html_url_in_code_preserved():
    """코드블록 안의 URL은 유지"""
    text = "```\nhttps://api.example.com/v1\n```"
    result = _md_to_telegram_html(text)
    assert "example.com" in result


# ---------------------------------------------------------------------------
# _md_to_telegram_html — 마크다운 변환
# ---------------------------------------------------------------------------

def test_html_bold():
    result = _md_to_telegram_html("**볼드**")
    assert "<b>볼드</b>" in result


def test_html_italic():
    result = _md_to_telegram_html("*이탤릭*")
    assert "<i>이탤릭</i>" in result


def test_html_header():
    result = _md_to_telegram_html("## 제목")
    assert "<b>제목</b>" in result


def test_html_code_block():
    result = _md_to_telegram_html("```python\nprint('hi')\n```")
    assert "<pre>" in result
    assert "print" in result


def test_html_inline_code():
    result = _md_to_telegram_html("변수 `foo`를 사용")
    assert "<code>foo</code>" in result


def test_html_strikethrough():
    result = _md_to_telegram_html("~~취소선~~")
    assert "<s>취소선</s>" in result


def test_html_blockquote():
    result = _md_to_telegram_html("> 인용문")
    assert "<blockquote>" in result
    assert "인용문" in result


def test_html_table_converted():
    """테이블이 리스트로 변환되는지"""
    text = "| Key | Value |\n|---|---|\n| A | 1 |"
    result = _md_to_telegram_html(text)
    assert "|" not in result.replace("</", "")  # HTML 태그 제외
    assert "A: 1" in result


# ---------------------------------------------------------------------------
# _md_to_telegram_html — 엣지 케이스
# ---------------------------------------------------------------------------

def test_html_empty():
    assert _md_to_telegram_html("") == ""


def test_html_plain_text():
    result = _md_to_telegram_html("그냥 텍스트")
    assert "그냥 텍스트" in result


def test_html_nested_bold_italic():
    result = _md_to_telegram_html("***볼드이탤릭***")
    assert "<b><i>볼드이탤릭</i></b>" in result


def test_html_multiple_urls():
    text = "https://a.com 그리고 https://b.com 끝"
    result = _md_to_telegram_html(text)
    assert "https://" not in result


# ---------------------------------------------------------------------------
# _split_message
# ---------------------------------------------------------------------------

def test_split_short():
    """짧은 메시지는 분할 안 함"""
    assert _split_message("짧은 텍스트") == ["짧은 텍스트"]


def test_split_long():
    """긴 메시지 분할 — 페이지 표시 '(N/M)' 포함해서 4096 이내"""
    long_text = "테스트 문장입니다.\n\n" * 500
    chunks = _split_message(long_text, max_len=4000)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 4096  # max_len + 페이지 표시 여유


def test_split_preserves_content():
    """분할 후 합치면 원본과 (대략) 일치"""
    text = "문단 1\n\n문단 2\n\n문단 3"
    chunks = _split_message(text, max_len=20)
    joined = "".join(chunks)
    assert "문단 1" in joined
    assert "문단 3" in joined


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  OK  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")

#!/usr/bin/env python3
"""filter_assistant_text 단위 테스트"""
import sys
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/workspace/supervisor")

from importlib.machinery import SourceFileLoader
mod = SourceFileLoader("relay", "D:/workspace/supervisor/relay-tool-use.py").load_module()
filter_assistant_text = mod.filter_assistant_text

passed = 0
failed = 0

def test(name, input_text, expected_contains=None, expected_not_contains=None, expected_empty=False):
    global passed, failed
    result = filter_assistant_text(input_text)
    ok = True

    if expected_empty and result != "":
        print(f"  FAIL {name} — 빈 결과 기대했으나: {repr(result[:80])}")
        ok = False
    if expected_contains:
        for s in expected_contains:
            if s not in result:
                print(f"  FAIL {name} — '{s}' 포함 기대")
                ok = False
    if expected_not_contains:
        for s in expected_not_contains:
            if s in result:
                print(f"  FAIL {name} — '{s}' 미포함 기대")
                ok = False
    if ok:
        print(f"  OK   {name}")
        passed += 1
    else:
        print(f"       결과: {repr(result[:200])}")
        failed += 1

# --- 테스트 ---

# 1. NemoNemo 로그 원본
test("nemonemo_log",
    "imports OK\n"
    "  OK  AUTO_RESUME_MODE == resume\n"
    "  OK  AUTO_RESUME_PROMPTS all modes\n"
    "  OK  PROJECTS\n"
    "Shell cwd was reset to D:\\workspace\\android\\NemoNemo\n"
    "OK  clean_control_chars\n"
    "  OK  clean_blank_lines\n"
    "  OK  clean_replacement\n"
    "  OK  escape_html\n"
    "  OK  escape_amp\n"
    "  OK  table_to_list\n"
    "  OK  no_table\n"
    "  OK  url_removed\n"
    "  OK  link_text_kept\n"
    "  OK  multiple_urls_removed\n"
    "  OK  code_url_preserved\n"
    "  OK  bold\n"
    "  OK  italic\n"
    "  OK  header\n"
    "  OK  inline_code\n"
    "  OK  strikethrough\n"
    "  OK  blockquote\n"
    "  OK  split_short\n"
    "  FAIL split_long\n"
    "  OK  split_max_len\n"
    "  OK  empty\n"
    "\n"
    "20 passed, 1 failed\n"
    "Shell cwd was reset to D:\\workspace\\android\\NemoNemo\n"
    "20/21 통과. split_long만 실패\n"
    "\n"
    "smoke 테스트 문서 업데이트 중",
    expected_contains=["통과", "FAIL", "smoke 테스트"],
    expected_not_contains=["Shell cwd", "OK  clean_blank", "OK  bold", "OK  escape_html"]
)

# 2. 전부 통과
test("all_pass",
    "OK  test_a\n  OK  test_b\n  OK  test_c\n\n3 passed",
    expected_contains=["3/3 통과", "3 passed"],
    expected_not_contains=["OK  test_a"]
)

# 3. 일반 텍스트 (변경 없음)
test("normal_text",
    "파일을 수정하겠습니다.\n빌드를 실행합니다.",
    expected_contains=["파일을 수정", "빌드를 실행"]
)

# 4. 도구 표시 라인 제거
test("tool_indicator",
    "수정 완료.\n\u2500 \U0001f527 Read: supervisor.py (1669자)\n다음 단계로 진행합니다.",
    expected_contains=["수정 완료", "다음 단계"],
    expected_not_contains=["\U0001f527", "1669"]
)

# 5. Shell cwd만 (빈 결과)
test("shell_cwd_only",
    "Shell cwd was reset to D:\\workspace",
    expected_empty=True
)

# 6. 여러 FAIL
test("multiple_fail",
    "OK  a\n  OK  b\n  FAIL c\n  FAIL d\n  OK  e\n\n결과 확인",
    expected_contains=["3/5 통과", "FAIL c", "FAIL d", "결과 확인"],
    expected_not_contains=["OK  a", "OK  b"]
)

# 7. imports OK 라인 (일반 텍스트로 유지)
test("imports_ok",
    "imports OK\n  OK  CONFIG_A\n  OK  CONFIG_B",
    expected_contains=["imports OK", "2/2 통과"],
    expected_not_contains=["OK  CONFIG_A"]
)

# 8. 빈 텍스트
test("empty_text", "", expected_empty=True)

# 9. FAIL만 있는 경우
test("fail_only",
    "FAIL test_x\n  FAIL test_y",
    expected_contains=["0/2 통과", "FAIL test_x", "FAIL test_y"]
)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

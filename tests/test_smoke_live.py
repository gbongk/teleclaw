"""TeleClaw 스모크 테스트 — 실제 SDK 연결로 기본 동작 검증.

실행: python tests/test_smoke_live.py
또는: python -m pytest tests/test_smoke_live.py -v (SDK 연결 필요)
"""

import asyncio
import json
import os
import sys
import time

import pytest

# --- 경로 / 인코딩 설정 ---
TELECLAW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TELECLAW_DIR)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- SDK import (실패 시 전체 스킵) ---
try:
    # conftest의 mock이 아닌 실제 SDK를 사용해야 하므로 직접 import
    if "claude_agent_sdk" in sys.modules:
        mod = sys.modules["claude_agent_sdk"]
        # mock 모듈이면 제거하고 실제 SDK를 로드
        if not hasattr(mod, "__file__") or mod.__file__ is None:
            del sys.modules["claude_agent_sdk"]
            if "claude_agent_sdk.types" in sys.modules:
                del sys.modules["claude_agent_sdk.types"]

    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
    )

    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False

# SDK 없으면 모듈 전체 스킵
pytestmark = pytest.mark.skipif(not SDK_AVAILABLE, reason="claude_agent_sdk 미설치")

# --- 상수 ---
TIMEOUT = 30  # 각 테스트 타임아웃 (초)
CWD = TELECLAW_DIR


# --- 헬퍼 ---

def _load_mcp_servers() -> dict:
    """MCP 서버 설정을 .mcp.json에서 로드."""
    mcp_path = os.path.join(TELECLAW_DIR, ".mcp.json")
    if os.path.exists(mcp_path):
        with open(mcp_path, "r", encoding="utf-8") as f:
            return json.load(f).get("mcpServers", {})
    return {}


async def _create_client(max_turns: int = 3) -> ClaudeSDKClient:
    """SDK 클라이언트 생성 + 연결."""
    options = ClaudeAgentOptions(
        max_turns=max_turns,
        system_prompt="스모크 테스트 모드. 간결하게 답하라.",
        permission_mode="bypassPermissions",
        cwd=CWD,
        mcp_servers=_load_mcp_servers(),
    )
    client = ClaudeSDKClient(options)
    await client.connect()
    return client


async def _query_and_collect(client: ClaudeSDKClient, prompt: str) -> list:
    """query 후 모든 메시지를 수집해서 리스트로 반환."""
    await client.query(prompt)
    messages = []
    async for msg in client.receive_messages():
        messages.append(msg)
        if isinstance(msg, ResultMessage):
            break
    return messages


def _extract_text(messages: list) -> str:
    """메시지 리스트에서 AssistantMessage의 텍스트를 합쳐서 반환."""
    parts = []
    for msg in messages:
        if isinstance(msg, AssistantMessage) and hasattr(msg, "content"):
            content = msg.content
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "text") and block.text:
                        parts.append(block.text)
            elif isinstance(content, str):
                parts.append(content)
    return "\n".join(parts)


def _has_tool_use(messages: list) -> bool:
    """메시지 리스트에 ToolUseBlock이 포함되어 있는지 확인."""
    for msg in messages:
        if hasattr(msg, "content") and isinstance(msg.content, list):
            for block in msg.content:
                if type(block).__name__ == "ToolUseBlock":
                    return True
    return False


# --- 테스트 ---

@pytest.mark.asyncio
@pytest.mark.timeout(TIMEOUT)
async def test_basic_response():
    """일반 메시지에 텍스트 응답이 오는지 (빈 응답 아님)."""
    client = await _create_client(max_turns=1)
    try:
        messages = await asyncio.wait_for(
            _query_and_collect(client, "안녕, OK라고만 답해."),
            timeout=TIMEOUT,
        )
        text = _extract_text(messages)
        assert len(messages) > 0, "메시지가 하나도 오지 않음"
        assert len(text.strip()) > 0, f"응답 텍스트가 비어 있음: {text!r}"
        print(f"  [PASS] 응답: {text.strip()[:80]}")
    finally:
        if hasattr(client, "disconnect"):
            await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.timeout(TIMEOUT)
async def test_agent_result():
    """에이전트 실행 후 결과가 오는지 (도구 호출 + 값 포함)."""
    client = await _create_client(max_turns=5)
    try:
        prompt = (
            f"{CWD}/src/config.py 에서 HEALTH_CHECK_INTERVAL 값을 알려줘. "
            "숫자만 답해."
        )
        messages = await asyncio.wait_for(
            _query_and_collect(client, prompt),
            timeout=TIMEOUT,
        )
        text = _extract_text(messages)
        assert len(messages) > 0, "메시지가 하나도 오지 않음"
        assert _has_tool_use(messages), "도구 호출(Agent)이 발생하지 않음"
        assert "120" in text, f"결과에 '120' 미포함: {text[:200]}"
        print(f"  [PASS] 에이전트 결과: {text.strip()[:80]}")
    finally:
        if hasattr(client, "disconnect"):
            await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.timeout(TIMEOUT)
async def test_slash_context():
    """/context 명령어가 동작하는지 (SDK 직접 실행)."""
    client = await _create_client(max_turns=1)
    try:
        messages = await asyncio.wait_for(
            _query_and_collect(client, "/context"),
            timeout=TIMEOUT,
        )
        text = _extract_text(messages)
        assert len(messages) > 0, "메시지가 하나도 오지 않음"
        assert "Context" in text or "Token" in text or "token" in text, f"/context 응답에 컨텍스트 정보 없음: {text[:200]}"
        print(f"  [PASS] /context 응답: {text.strip()[:80]}")
    finally:
        if hasattr(client, "disconnect"):
            await client.disconnect()


def test_teleclaw_log_no_errors():
    """TeleClaw 로그에 치명적 에러가 없는지 확인."""
    log_path = os.path.join(TELECLAW_DIR, "logs", "teleclaw.log")
    if not os.path.exists(log_path):
        pytest.skip("로그 파일 없음")
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()[-100:]  # 최근 100줄
    fatal_keywords = ["Traceback", "FATAL", "크래시"]
    errors = [l.strip() for l in lines if any(k in l for k in fatal_keywords)]
    assert len(errors) == 0, f"로그에 치명적 에러 {len(errors)}건:\n" + "\n".join(errors[:5])
    # 빈 응답 카운트
    empty_count = sum(1 for l in lines if "빈 응답" in l and "폴백" not in l)
    print(f"  [PASS] 최근 100줄: 치명적 에러 0건, 빈 응답 {empty_count}건")


def test_teleclaw_log_agent_results():
    """TeleClaw 로그에서 에이전트 결과가 정상 처리되었는지."""
    log_path = os.path.join(TELECLAW_DIR, "logs", "teleclaw.log")
    if not os.path.exists(log_path):
        pytest.skip("로그 파일 없음")
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()[-200:]
    started = sum(1 for l in lines if "[agent] started" in l)
    completed = sum(1 for l in lines if "[agent] completed" in l or "output 직접 표시" in l)
    result_added = sum(1 for l in lines if "[agent] result added" in l)
    print(f"  [INFO] 에이전트: started={started}, completed={completed}, result_added={result_added}")
    if started > 0:
        assert completed > 0, f"에이전트 {started}개 시작됐지만 완료 0건"
    print(f"  [PASS] 에이전트 로그 정상")


# --- 독립 실행 지원 ---

async def _run_standalone():
    """pytest 없이 직접 실행할 때."""
    tests = [
        ("기본 응답", test_basic_response),
        ("에이전트 결과", test_agent_result),
        ("/context 명령어", test_slash_context),
    ]

    results = {"PASS": 0, "FAIL": 0, "SKIP": 0}

    print("=" * 50)
    print("TeleClaw 스모크 테스트 (Live SDK)")
    print("=" * 50)

    if not SDK_AVAILABLE:
        print("SKIP: claude_agent_sdk 미설치")
        return

    for name, test_fn in tests:
        print(f"\n[{name}]")
        try:
            await asyncio.wait_for(test_fn(), timeout=TIMEOUT)
            results["PASS"] += 1
        except asyncio.TimeoutError:
            print(f"  [FAIL] 타임아웃 ({TIMEOUT}초)")
            results["FAIL"] += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            results["FAIL"] += 1
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            results["FAIL"] += 1

    # 로그 검증 (비동기 아님)
    for name, test_fn in [("로그 에러 검사", test_teleclaw_log_no_errors), ("로그 에이전트 검사", test_teleclaw_log_agent_results)]:
        print(f"\n[{name}]")
        try:
            test_fn()
            results["PASS"] += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            results["FAIL"] += 1

    print("\n" + "=" * 50)
    total = sum(results.values())
    print(f"결과: {results['PASS']}/{total} PASS, "
          f"{results['FAIL']} FAIL, {results['SKIP']} SKIP")
    if results["FAIL"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_run_standalone())

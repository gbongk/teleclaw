"""
SDK 직접 연결 테스트 — TeleClaw 없이 순수 SDK 동작 확인.

사용법:
    cd D:/workspace/teleclaw
    python tests/live_sdk_test.py "mcp__ai-chat__ask_ai" '{"provider":"duckduckgo","prompt":"1+1=?"}'

출력: 수신된 모든 SDK 메시지를 타입/내용과 함께 출력.
결과: logs/live_sdk_{timestamp}.jsonl 에 전수 기록.
"""
import asyncio
import json
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


async def main():
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
    from claude_agent_sdk import AssistantMessage, UserMessage, ResultMessage

    # 인자 파싱
    tool_call = None
    prompt = "테스트입니다. OK만 답해."
    if len(sys.argv) > 1:
        prompt = sys.argv[1]
        if len(sys.argv) > 2:
            tool_call = (sys.argv[1], json.loads(sys.argv[2]))
            prompt = f"도구 {tool_call[0]}을 호출해서 결과를 보여줘: {json.dumps(tool_call[1], ensure_ascii=False)}"

    # MCP 서버 설정 로드
    mcp_servers = {}
    mcp_json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "converter", ".mcp.json")
    if not os.path.exists(mcp_json_path):
        # 대안: 현재 디렉토리
        mcp_json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".mcp.json")
    if os.path.exists(mcp_json_path):
        with open(mcp_json_path, "r", encoding="utf-8") as f:
            mcp_data = json.load(f)
        mcp_servers = mcp_data.get("mcpServers", {})
        print(f"MCP 서버: {list(mcp_servers.keys())}")
    else:
        print(f"⚠️ MCP 설정 없음 ({mcp_json_path})")

    # SDK 연결
    options = ClaudeAgentOptions(
        max_turns=3,
        system_prompt="테스트용. 도구 호출이 요청되면 해당 도구를 호출하고 결과를 그대로 보여줘.",
        permission_mode="bypassPermissions",
        cwd=os.path.dirname(os.path.dirname(__file__)),
        mcp_servers=mcp_servers,
    )

    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", f"live_sdk_{ts}.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")

    print(f"=== SDK 직접 연결 테스트 ===")
    print(f"프롬프트: {prompt}")
    print(f"로그: {log_path}")
    print(f"---")

    client = ClaudeSDKClient(options)
    await client.connect()
    await client.query(prompt)

    msg_count = 0
    async for sdk_msg in client.receive_messages():
        msg_count += 1
        msg_type = type(sdk_msg).__name__

        # 로그 기록
        entry = {
            "seq": msg_count,
            "timestamp": time.time(),
            "type": msg_type,
            "raw": str(vars(sdk_msg))[:2000],
        }

        # 블록 상세
        blocks = []
        if hasattr(sdk_msg, "content"):
            content = sdk_msg.content
            if isinstance(content, list):
                for block in content:
                    btype = type(block).__name__
                    binfo = {"type": btype}
                    if hasattr(block, "name"):
                        binfo["name"] = block.name
                    if hasattr(block, "text"):
                        binfo["text"] = str(block.text)[:200]
                    if hasattr(block, "content"):
                        binfo["content"] = str(block.content)[:200]
                    if hasattr(block, "thinking"):
                        binfo["thinking"] = str(block.thinking)[:200]
                    if hasattr(block, "tool_use_id"):
                        binfo["tool_use_id"] = block.tool_use_id
                    if hasattr(block, "id"):
                        binfo["id"] = block.id
                    blocks.append(binfo)
        entry["blocks"] = blocks

        # ResultMessage 필드
        if hasattr(sdk_msg, "result"):
            entry["result"] = str(sdk_msg.result)[:500] if sdk_msg.result else None
        if hasattr(sdk_msg, "session_id"):
            entry["session_id"] = sdk_msg.session_id

        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log_file.flush()

        # 콘솔 출력
        print(f"[{msg_count}] {msg_type}")
        if blocks:
            for b in blocks:
                btype = b["type"]
                if btype == "ToolUseBlock":
                    print(f"     ToolUse: {b.get('name', '?')} id={b.get('id', '?')[:16]}")
                elif btype == "ToolResultBlock":
                    print(f"     ToolResult: tuid={b.get('tool_use_id', '?')[:16]} content={b.get('content', '')[:80]}")
                elif btype == "TextBlock":
                    print(f"     Text: {b.get('text', '')[:80]}")
                elif btype == "ThinkingBlock":
                    print(f"     Thinking: ({len(b.get('thinking', ''))}자)")
                else:
                    print(f"     {btype}: {str(b)[:80]}")
        if hasattr(sdk_msg, "result") and sdk_msg.result:
            print(f"     result: {str(sdk_msg.result)[:100]}")
        if isinstance(sdk_msg, ResultMessage):
            print(f"--- 스트림 종료 (ResultMessage) ---")
            break
        print()

    log_file.close()
    print(f"\n=== 완료: {msg_count}개 메시지 수신 ===")
    print(f"로그 저장: {log_path}")


if __name__ == "__main__":
    asyncio.run(main())

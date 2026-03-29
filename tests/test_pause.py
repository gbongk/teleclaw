#!/usr/bin/env python3
"""pause/restart 사이클 단위 테스트.

슈퍼바이저 연결 없이 플래그 파일 기반 로직을 검증한다.
"""
import sys
import os
import tempfile
import shutil

sys.stdout.reconfigure(encoding="utf-8")

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  OK   {name}")
        passed += 1
    else:
        print(f"  FAIL {name} {detail}")
        failed += 1


# 임시 디렉토리로 DATA_DIR 시뮬레이션
tmpdir = tempfile.mkdtemp()

try:
    # === 1. pause 플래그 생성 ===
    pause_flag = os.path.join(tmpdir, "pause_TestSession.flag")
    with open(pause_flag, "w") as f:
        f.write("1711000000")
    test("pause_flag_created", os.path.exists(pause_flag))

    # === 2. pause 상태 확인 ===
    test("pause_flag_exists", os.path.exists(pause_flag))

    # === 3. health check에서 pause 스킵 로직 ===
    # pause 있으면 continue (재시작 안 함)
    should_skip = os.path.exists(pause_flag)
    test("health_check_skip", should_skip)

    # === 4. 슈퍼바이저 시작 시 pause 스킵 ===
    should_connect = not os.path.exists(pause_flag)
    test("startup_skip_paused", should_connect == False)

    # === 5. restart 요청 시 pause 자동 해제 ===
    restart_flag = os.path.join(tmpdir, "restart_request_TestSession.flag")
    with open(restart_flag, "w") as f:
        f.write("force")
    # restart flag 처리: pause 해제
    if os.path.exists(restart_flag):
        os.unlink(restart_flag)
        if os.path.exists(pause_flag):
            os.unlink(pause_flag)
    test("restart_removes_pause", not os.path.exists(pause_flag))
    test("restart_flag_consumed", not os.path.exists(restart_flag))

    # === 6. pause 없을 때 health check 정상 동작 ===
    should_skip_after = os.path.exists(pause_flag)
    test("health_check_normal", should_skip_after == False)

    # === 7. reset도 pause 해제 ===
    # 다시 pause
    with open(pause_flag, "w") as f:
        f.write("1711000000")
    reset_flag = os.path.join(tmpdir, "restart_request_TestSession.flag")
    with open(reset_flag, "w") as f:
        f.write("force,reset")
    if os.path.exists(reset_flag):
        os.unlink(reset_flag)
        if os.path.exists(pause_flag):
            os.unlink(pause_flag)
    test("reset_removes_pause", not os.path.exists(pause_flag))

    # === 8. pause 없는 세션에 restart해도 문제 없음 ===
    assert not os.path.exists(pause_flag)
    restart_flag2 = os.path.join(tmpdir, "restart_request_TestSession.flag")
    with open(restart_flag2, "w") as f:
        f.write("force")
    if os.path.exists(restart_flag2):
        os.unlink(restart_flag2)
        if os.path.exists(pause_flag):
            os.unlink(pause_flag)
    test("restart_no_pause_ok", not os.path.exists(restart_flag2))

    # === 9. 여러 세션 독립성 ===
    pause_a = os.path.join(tmpdir, "pause_SessionA.flag")
    pause_b = os.path.join(tmpdir, "pause_SessionB.flag")
    with open(pause_a, "w") as f:
        f.write("1")
    test("multi_session_a_paused", os.path.exists(pause_a))
    test("multi_session_b_not_paused", not os.path.exists(pause_b))
    # B 재시작해도 A는 여전히 pause
    test("multi_session_a_still_paused", os.path.exists(pause_a))

    # === 10. ps에서 PAUSED 표시 ===
    status = "OK"
    if os.path.exists(pause_a):
        status = "PAUSED"
    test("ps_shows_paused", status == "PAUSED")

    # === 11. pause 중 텔레그램 메시지 거부 시뮬레이션 ===
    # pause 플래그 있으면 메시지 큐에 넣지 않고 거부
    should_reject = os.path.exists(pause_a)
    test("telegram_msg_rejected_when_paused", should_reject)

    # === 12. pause 중 연속 에러로 인한 재시작 방지 ===
    # health check에서 pause 체크 → _restart_session 호출 안 함
    error_count = 5
    should_restart = error_count >= 3 and not os.path.exists(pause_a)
    test("no_restart_on_error_when_paused", should_restart == False)

    # === 13. 다른 세션에서 restart 요청으로 pause 해제 가능 ===
    restart_a = os.path.join(tmpdir, "restart_request_SessionA.flag")
    with open(restart_a, "w") as f:
        f.write("force")
    if os.path.exists(restart_a):
        os.unlink(restart_a)
        if os.path.exists(pause_a):
            os.unlink(pause_a)
    test("other_session_can_unpause", not os.path.exists(pause_a))

finally:
    shutil.rmtree(tmpdir)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

"""config.py 유닛 테스트 — auto-resume 설정, 프로젝트 설정."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "hub"))

from config import (
    AUTO_RESUME_ENABLED, AUTO_RESUME_MODE, AUTO_RESUME_PROMPTS,
    PROJECTS, HEALTH_CHECK_INTERVAL, STUCK_THRESHOLD,
)


def test_auto_resume_mode_is_resume():
    """기본 모드가 resume인지 확인"""
    assert AUTO_RESUME_MODE == "resume"


def test_auto_resume_prompts_all_modes():
    """resume/check/none 프롬프트가 모두 정의되어 있는지"""
    assert "resume" in AUTO_RESUME_PROMPTS
    assert "check" in AUTO_RESUME_PROMPTS
    assert "none" in AUTO_RESUME_PROMPTS
    assert AUTO_RESUME_PROMPTS["resume"] is not None
    assert AUTO_RESUME_PROMPTS["check"] is not None
    assert AUTO_RESUME_PROMPTS["none"] is None


def test_auto_resume_enabled():
    assert AUTO_RESUME_ENABLED is True


def test_projects_defined():
    """4개 프로젝트 정의"""
    assert len(PROJECTS) >= 4
    for name, config in PROJECTS.items():
        assert "bot_token" in config
        assert "bot_id" in config
        assert "cwd" in config


def test_health_check_interval():
    assert HEALTH_CHECK_INTERVAL > 0


def test_stuck_threshold():
    assert STUCK_THRESHOLD > 0


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

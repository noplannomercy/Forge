"""Unit tests for refine/validator.py (REFINE-04).

The validator is a pure synchronous class. Tests pull the default config
from ``REFINE_RULE_DEFAULTS["validator"]`` where possible so tests stay
aligned with the seeded production thresholds.
"""

from __future__ import annotations

from job_store import REFINE_RULE_DEFAULTS
from refine.validator import GateVerdict, Validator


# Shared config matching the seeded defaults — tests that need custom
# thresholds build their own dict.
DEFAULT_CONFIG = {
    "require_utf8": True,
    "min_newlines": 1,
    "min_korean_ratio": 0.1,
    "min_length": 100,
}


def _korean_doc(min_length: int = 120) -> str:
    """Build a realistic Korean markdown document of at least ``min_length``
    characters with at least one newline."""
    # Two-line Korean paragraph — each copy contributes ~30 Hangul chars and
    # one newline. We duplicate until we pass the requested length.
    block = "한국어 문서 테스트입니다.\n추가 설명 문장을 붙입니다.\n"
    while len(block) < min_length:
        block += "추가 한국어 문장을 덧붙여 충분한 길이를 확보합니다.\n"
    return block


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------

def test_pass_all_thresholds():
    v = Validator(DEFAULT_CONFIG)
    text = _korean_doc()
    verdict = v.check(text)
    assert isinstance(verdict, GateVerdict)
    assert verdict.passed is True
    assert verdict.reason is None
    assert verdict.checks["utf8"] is True
    assert verdict.checks["newlines"] >= DEFAULT_CONFIG["min_newlines"]
    assert verdict.checks["korean_ratio"] >= DEFAULT_CONFIG["min_korean_ratio"]
    assert verdict.checks["length"] >= DEFAULT_CONFIG["min_length"]


# ---------------------------------------------------------------------------
# failure paths — each verifies reason mentions the right field
# ---------------------------------------------------------------------------

def test_fail_korean_ratio_below_threshold():
    v = Validator(DEFAULT_CONFIG)
    # English-only, long enough and with newlines so other checks pass first
    # would fail; korean_ratio is the one we want to trip.
    text = (
        "This document is written entirely in English and should fail the "
        "korean ratio gate because it contains zero Hangul syllables.\n"
        "Second line keeps the newline gate satisfied for this test.\n"
        "Third line pads the length beyond the minimum threshold.\n"
    )
    verdict = v.check(text)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "korean_ratio" in verdict.reason
    assert verdict.checks["korean_ratio"] == 0.0


def test_fail_min_newlines():
    v = Validator({**DEFAULT_CONFIG, "min_newlines": 1})
    # Single-line Korean doc — no '\n' at all.
    text = "한국어 문서인데 줄바꿈이 전혀 없는 매우 긴 한 줄짜리 텍스트입니다." * 5
    verdict = v.check(text)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "newlines" in verdict.reason
    assert verdict.checks["newlines"] == 0


def test_fail_min_length():
    v = Validator(DEFAULT_CONFIG)
    # Short Korean doc with a newline and enough korean ratio, but below
    # min_length (100).
    text = "한국어 짧은 문서.\n"
    verdict = v.check(text)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "length" in verdict.reason
    assert verdict.checks["length"] == len(text)


def test_empty_text():
    v = Validator(DEFAULT_CONFIG)
    # Empty string — no ZeroDivisionError thanks to `total = len(text) or 1`.
    # Fails the newlines check first (0 < 1) under default config.
    verdict = v.check("")
    assert verdict.passed is False
    assert verdict.reason is not None
    # korean_ratio must be computable without crashing.
    assert verdict.checks["korean_ratio"] == 0.0
    assert verdict.checks["newlines"] == 0
    assert verdict.checks["length"] == 0


def test_checks_dict_always_populated():
    """Even on short-circuit failure, all four check keys are present."""
    v = Validator(DEFAULT_CONFIG)
    # Trip on the first gate (newlines) to ensure later gates still populated.
    verdict = v.check("한글")
    assert verdict.passed is False
    for key in ("utf8", "newlines", "korean_ratio", "length"):
        assert key in verdict.checks, f"missing key {key} in checks"


# ---------------------------------------------------------------------------
# boundary / integration
# ---------------------------------------------------------------------------

def test_boundary_exact_min():
    """Text exactly at each minimum should pass — comparator is `<`, not `<=`."""
    # Build text with exactly min_newlines=1, length exactly 100,
    # and korean_ratio exactly 0.1.
    config = {
        "require_utf8": True,
        "min_newlines": 1,
        "min_korean_ratio": 0.1,
        "min_length": 100,
    }
    # 10 Hangul chars + 89 ASCII chars + 1 newline = 100 chars, 1 newline,
    # ratio = 10 / 100 = 0.1 (exactly at threshold).
    hangul = "한국어테스트입니다"  # 9 chars
    hangul += "가"  # pad to 10
    assert len(hangul) == 10
    ascii_pad = "a" * 89
    text = hangul + ascii_pad + "\n"
    assert len(text) == 100
    assert text.count("\n") == 1

    v = Validator(config)
    verdict = v.check(text)
    assert verdict.passed is True, f"expected pass at exact boundaries: {verdict}"
    assert verdict.reason is None
    assert verdict.checks["newlines"] == 1
    assert verdict.checks["length"] == 100
    # ratio is rounded to 3 decimals — 0.1 exactly.
    assert verdict.checks["korean_ratio"] == 0.1


def test_uses_defaults_from_store():
    """Integration: use REFINE_RULE_DEFAULTS['validator'] directly.

    Confirms the defaults dict (sans a 'version' key — seeded version lives
    only in the store row) is accepted by Validator and a typical Korean
    document passes.
    """
    config = REFINE_RULE_DEFAULTS["validator"]
    assert "version" not in config  # sanity: store row carries version, not config
    v = Validator(config)
    verdict = v.check(_korean_doc())
    assert verdict.passed is True
    assert verdict.reason is None


# ---------------------------------------------------------------------------
# nice-to-have — mixed Hangul + Hanja
# ---------------------------------------------------------------------------

def test_mixed_hangul_hanja():
    """Hanja (CJK Unified Ideographs) must NOT count toward korean_ratio.

    Only Hangul Syllables (U+AC00–U+D7A3) are counted; so a document with
    lots of Hanja but few Hangul can still fail the ratio gate.
    """
    v = Validator(DEFAULT_CONFIG)
    # 2 Hangul chars + 30 Hanja chars + newline + padding so length check
    # does not trip first.
    hangul = "한글"  # 2 Hangul
    hanja = "漢字" * 15  # 30 Hanja (U+6F22, U+5B57)
    # Confirm our hanja are outside the Hangul Syllables block.
    for ch in hanja:
        assert not (0xAC00 <= ord(ch) <= 0xD7A3)
    # Pad with ASCII so length passes (>= 100).
    text = hangul + hanja + "\n" + ("a" * 70) + "\n"
    assert len(text) >= 100
    verdict = v.check(text)
    # Only 2 Hangul counted — ratio = 2 / len(text) ~ 0.019 < 0.1.
    assert verdict.passed is False
    assert "korean_ratio" in (verdict.reason or "")
    # Explicit sanity: hanja did not bump the ratio past threshold.
    assert verdict.checks["korean_ratio"] < 0.1

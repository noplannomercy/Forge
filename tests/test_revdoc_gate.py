"""Tests for revdoc.gate (REVDOC-05).

Covers the two-check pipeline (sections > length), priority order,
and the feedback/details contract.
"""

from __future__ import annotations


from revdoc.gate import REQUIRED_SECTIONS, GateVerdict, RevdocGate


def _valid_md(length: int = 900) -> str:
    """Build a reverse-doc MD that passes every check.

    The body is padded with ASCII filler so we can dial the length
    above/below the gate's ``min_length`` threshold deterministically.
    """
    head = (
        "## 업무목적\n본 코드는 고객 등급 산출 로직을 구현한다.\n\n"
        "## 처리흐름\n1. 입력 수신\n2. 규칙 평가\n3. 결과 반환\n\n"
        "## 입력/출력\n- 입력: customer_id (str)\n- 출력: tier (str)\n\n"
        "## 규칙/예외\n- total_amount > 1000 이면 GOLD\n- 예외 시 BRONZE\n\n"
        "## 근거\n사내 고객 정책 문서 R-001 근거로 작성.\n\n"
        "## 추적성\n이 코드는 R-001 고객 등급 산출 업무 규칙을 구현하며, "
        "근거는 사내 정책 문서에서 확인할 수 있다.\n\n"
        "## 관련업무\n- 선행: 주문 집계\n- 후행: 혜택 부여\n"
    )
    # Pad body with filler inside the 관련업무 section to grow length.
    pad = "x" * max(0, length - len(head))
    return head + pad


def test_gate_pass_minimal():
    """MD with all 7 sections and length >= 500 passes."""
    gate = RevdocGate()
    md = _valid_md(length=900)
    verdict = gate.check(md)
    assert verdict.passed is True
    assert verdict.reason is None
    assert verdict.feedback is None
    assert verdict.details["missing_sections"] == []
    assert verdict.details["length"] >= 500


def test_gate_fail_missing_section():
    """Dropping 처리흐름 must fail with reason/feedback mentioning it."""
    gate = RevdocGate()
    md = _valid_md(length=900).replace(
        "## 처리흐름\n1. 입력 수신\n2. 규칙 평가\n3. 결과 반환\n\n", ""
    )
    verdict = gate.check(md)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "missing" in verdict.reason
    assert "처리흐름" in verdict.reason
    assert verdict.feedback is not None
    assert "처리흐름" in verdict.feedback
    assert verdict.details["missing_sections"] == ["처리흐름"]


def test_gate_fail_length_under_500():
    """All sections present, but length < 500 → length failure."""
    gate = RevdocGate()
    md = _valid_md(length=300)
    # Sanity: explicit floor so the test is not subtly broken by future
    # template growth pushing the un-padded body above 500.
    assert len(md) < 500
    verdict = gate.check(md)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "length" in verdict.reason
    assert verdict.feedback is not None
    # Earlier checks must have populated their details fields.
    assert verdict.details["missing_sections"] == []
    assert verdict.details["length"] == len(md)


def test_gate_fail_priority_order():
    """When multiple checks would fail, section check wins (highest priority).

    Construct MD missing a section AND well under 500 chars.
    The reason must mention sections, not length.
    """
    gate = RevdocGate()
    md = (
        "## 업무목적\n짧다.\n\n"
        "## 입력/출력\n- a\n\n"
        "## 규칙/예외\n- b\n\n"
        "## 근거\n없음.\n\n"
        "## 추적성\n자유 서술.\n\n"
        "## 관련업무\n- e\n"
    )
    # Sanity: this MD should fail section + length checks.
    assert "## 처리흐름" not in md  # section missing
    assert len(md) < 500  # length short

    verdict = gate.check(md)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "missing" in verdict.reason
    # Priority: must NOT fall through to length.
    assert "length" not in verdict.reason
    # Details contract: only section-phase measurements present.
    assert "missing_sections" in verdict.details
    assert "처리흐름" in verdict.details["missing_sections"]
    assert "length" not in verdict.details


def test_gate_feedback_populated_on_failure():
    """Every failure type must produce a non-empty, actionable feedback string."""
    gate = RevdocGate()

    # Failure type 1: missing section.
    md_no_section = _valid_md(length=900).replace("## 관련업무\n", "## XXX\n")
    v1 = gate.check(md_no_section)
    assert v1.passed is False
    assert v1.feedback is not None and len(v1.feedback) > 10
    assert "섹션" in v1.feedback or "section" in v1.feedback.lower()

    # Failure type 2: length.
    md_short = _valid_md(length=200)
    v2 = gate.check(md_short)
    assert v2.passed is False
    assert v2.feedback is not None and len(v2.feedback) > 10
    assert "짧" in v2.feedback or "길이" in v2.feedback or "자" in v2.feedback


def test_gate_details_always_populated():
    """``details`` dict is always a dict; its shape depends on which check fired.

    Contract:
    * On pass: both keys present — ``missing_sections`` (empty list), ``length`` (int).
    * On section failure: only ``missing_sections``.
    * On length failure: both keys.
    """
    gate = RevdocGate()

    # Pass.
    v_pass = gate.check(_valid_md(length=900))
    assert isinstance(v_pass.details, dict)
    assert set(v_pass.details.keys()) == {"missing_sections", "length"}

    # Section failure.
    v_sec = gate.check(_valid_md(length=900).replace("## 관련업무\n", "## XXX\n"))
    assert isinstance(v_sec.details, dict)
    assert set(v_sec.details.keys()) == {"missing_sections"}

    # Length failure.
    v_len = gate.check(_valid_md(length=200))
    assert isinstance(v_len.details, dict)
    assert set(v_len.details.keys()) == {"missing_sections", "length"}


def test_gate_custom_min_length():
    """``RevdocGate(min_length=50)`` accepts compact input with all structure."""
    # Build a compact MD: every section present, aiming ~75 chars.
    md = (
        "## 업무목적\na\n"
        "## 처리흐름\nb\n"
        "## 입력/출력\nc\n"
        "## 규칙/예외\nd\n"
        "## 근거\ne\n"
        "## 추적성\n자유 서술.\n"
        "## 관련업무\nf\n"
    )
    assert len(md) >= 50
    # Default gate (min_length=500) must reject this.
    assert RevdocGate().check(md).passed is False
    # Custom gate must accept it.
    gate = RevdocGate(min_length=50)
    verdict = gate.check(md)
    assert verdict.passed is True, f"custom min_length should accept; verdict={verdict}"
    assert verdict.details["length"] == len(md)


def test_gate_required_sections_constant_matches_prompt():
    """Sanity: the 7-section constant mirrors the prompt template contract.

    A guard against accidental drift if someone edits one file but not
    the other.
    """
    assert REQUIRED_SECTIONS == [
        "업무목적",
        "처리흐름",
        "입력/출력",
        "규칙/예외",
        "근거",
        "추적성",
        "관련업무",
    ]


def test_gate_verdict_is_dataclass_shape():
    """``GateVerdict`` exposes the four documented fields."""
    v = GateVerdict(passed=True)
    assert v.passed is True
    assert v.details == {}
    assert v.reason is None
    assert v.feedback is None

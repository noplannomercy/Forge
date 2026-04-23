"""Tests for revdoc.gate (REVDOC-05).

Covers the three-check pipeline (sections > traceability > length),
priority order, fullwidth-colon tolerance, and the feedback/details
contract.
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
        "## 추적성\n"
        "- Rule: R-001 고객 등급 산출\n"
        "- Condition: total_amount > 1000 AND tier = 'GOLD'\n"
        "- Evidence: customer_tier.py:45\n\n"
        "## 관련업무\n- 선행: 주문 집계\n- 후행: 혜택 부여\n"
    )
    # Pad body with filler inside the 관련업무 section to grow length.
    pad = "x" * max(0, length - len(head))
    return head + pad


def test_gate_pass_minimal():
    """MD with all 7 sections, triangle present, length >= 800 passes."""
    gate = RevdocGate()
    md = _valid_md(length=900)
    verdict = gate.check(md)
    assert verdict.passed is True
    assert verdict.reason is None
    assert verdict.feedback is None
    assert verdict.details["missing_sections"] == []
    assert verdict.details["traceability"] == {
        "rule": True,
        "condition": True,
        "evidence": True,
    }
    assert verdict.details["length"] >= 800


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


def test_gate_fail_traceability_missing_rule():
    """All sections present but no Rule: → traceability failure."""
    gate = RevdocGate()
    md = _valid_md(length=900).replace(
        "- Rule: R-001 고객 등급 산출\n", ""
    )
    verdict = gate.check(md)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "traceability" in verdict.reason
    assert "Rule" in verdict.reason
    assert verdict.feedback is not None
    assert "Rule" in verdict.feedback
    # Sections check should have succeeded first.
    assert verdict.details["missing_sections"] == []
    assert verdict.details["traceability"]["rule"] is False
    assert verdict.details["traceability"]["condition"] is True
    assert verdict.details["traceability"]["evidence"] is True


def test_gate_fail_length_under_800():
    """All sections + triangle present, but length < 800 → length failure."""
    gate = RevdocGate()
    # _valid_md(length=500) caps padding to whatever keeps total ~500;
    # ensure below 800.
    md = _valid_md(length=500)
    # Sanity: explicit floor so the test is not subtly broken by future
    # template growth pushing the un-padded body above 800.
    assert len(md) < 800
    verdict = gate.check(md)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "length" in verdict.reason
    assert verdict.feedback is not None
    # Earlier checks must have populated their details fields.
    assert verdict.details["missing_sections"] == []
    assert verdict.details["traceability"] == {
        "rule": True,
        "condition": True,
        "evidence": True,
    }
    assert verdict.details["length"] == len(md)


def test_gate_fail_priority_order():
    """When multiple checks would fail, section check wins (highest priority).

    Construct MD missing a section AND missing Rule AND well under 800 chars.
    The reason must mention sections, not traceability or length.
    """
    gate = RevdocGate()
    md = (
        "## 업무목적\n짧다.\n\n"
        "## 입력/출력\n- a\n\n"
        "## 규칙/예외\n- b\n\n"
        "## 근거\n없음.\n\n"
        "## 추적성\n- Condition: c\n- Evidence: d\n\n"
        "## 관련업무\n- e\n"
    )
    # Sanity: this MD should fail all three checks if run in isolation.
    assert "## 처리흐름" not in md  # section missing
    assert "Rule:" not in md  # triangle broken
    assert len(md) < 800  # length short

    verdict = gate.check(md)
    assert verdict.passed is False
    assert verdict.reason is not None
    assert "missing" in verdict.reason
    # Priority: must NOT fall through to traceability or length.
    assert "traceability" not in verdict.reason
    assert "length" not in verdict.reason
    # Details contract: only section-phase measurements present.
    assert "missing_sections" in verdict.details
    assert "처리흐름" in verdict.details["missing_sections"]
    assert "traceability" not in verdict.details
    assert "length" not in verdict.details


def test_gate_accepts_korean_fullwidth_colon():
    """``Rule：`` / ``Condition：`` / ``Evidence：`` (U+FF1A) must match."""
    gate = RevdocGate()
    md = _valid_md(length=900)
    # Swap ASCII ':' for fullwidth '：' in the triangle block.
    md = md.replace("- Rule: R-001", "- Rule：R-001")
    md = md.replace("- Condition: total_amount", "- Condition：total_amount")
    md = md.replace("- Evidence: customer_tier.py:45", "- Evidence：customer_tier.py:45")
    assert "Rule：" in md and "Condition：" in md and "Evidence：" in md
    verdict = gate.check(md)
    assert verdict.passed is True, (
        f"fullwidth colon should be accepted; verdict={verdict}"
    )


def test_gate_feedback_populated_on_failure():
    """Every failure type must produce a non-empty, actionable feedback string."""
    gate = RevdocGate()

    # Failure type 1: missing section.
    md_no_section = _valid_md(length=900).replace("## 관련업무\n", "## XXX\n")
    v1 = gate.check(md_no_section)
    assert v1.passed is False
    assert v1.feedback is not None and len(v1.feedback) > 10
    assert "섹션" in v1.feedback or "section" in v1.feedback.lower()

    # Failure type 2: missing triangle piece.
    md_no_rule = _valid_md(length=900).replace("- Rule: R-001 고객 등급 산출\n", "")
    v2 = gate.check(md_no_rule)
    assert v2.passed is False
    assert v2.feedback is not None and len(v2.feedback) > 10
    assert "Rule" in v2.feedback

    # Failure type 3: length.
    md_short = _valid_md(length=400)
    v3 = gate.check(md_short)
    assert v3.passed is False
    assert v3.feedback is not None and len(v3.feedback) > 10
    assert "짧" in v3.feedback or "길이" in v3.feedback or "자" in v3.feedback


def test_gate_details_always_populated():
    """``details`` dict is always a dict; its shape depends on which check fired.

    Contract:
    * On pass: all three keys present — ``missing_sections`` (empty list),
      ``traceability`` (all True), ``length`` (int).
    * On section failure: only ``missing_sections``.
    * On traceability failure: ``missing_sections`` + ``traceability``.
    * On length failure: all three keys (same as pass).
    """
    gate = RevdocGate()

    # Pass.
    v_pass = gate.check(_valid_md(length=900))
    assert isinstance(v_pass.details, dict)
    assert set(v_pass.details.keys()) == {"missing_sections", "traceability", "length"}

    # Section failure.
    v_sec = gate.check(_valid_md(length=900).replace("## 관련업무\n", "## XXX\n"))
    assert isinstance(v_sec.details, dict)
    assert set(v_sec.details.keys()) == {"missing_sections"}

    # Traceability failure.
    v_tri = gate.check(
        _valid_md(length=900).replace("- Rule: R-001 고객 등급 산출\n", "")
    )
    assert isinstance(v_tri.details, dict)
    assert set(v_tri.details.keys()) == {"missing_sections", "traceability"}

    # Length failure.
    v_len = gate.check(_valid_md(length=400))
    assert isinstance(v_len.details, dict)
    assert set(v_len.details.keys()) == {"missing_sections", "traceability", "length"}


def test_gate_custom_min_length():
    """``RevdocGate(min_length=100)`` accepts 150-char-ish input with all structure."""
    # Build a compact MD: every section present + triangle, aiming ~150 chars.
    md = (
        "## 업무목적\na\n"
        "## 처리흐름\nb\n"
        "## 입력/출력\nc\n"
        "## 규칙/예외\nd\n"
        "## 근거\ne\n"
        "## 추적성\nRule: x\nCondition: y\nEvidence: z\n"
        "## 관련업무\nf\n"
    )
    assert len(md) >= 100
    # Default gate (min_length=800) must reject this.
    assert RevdocGate().check(md).passed is False
    # Custom gate must accept it.
    gate = RevdocGate(min_length=100)
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

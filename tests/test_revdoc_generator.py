"""Tests for :class:`revdoc.generator.ReverseDocGenerator` (T9).

Exercises the full orchestration loop:

* prompt loading from a seeded ``InMemoryPromptStore``;
* Gate-driven retry with feedback injection into the next prompt;
* Refiner application on pass (evidence: frontmatter gets stripped);
* "retries exhausted" terminal path with the last generation returned;
* ``model`` override propagation into ``VLMClient.process_text``;
* ``LookupError`` on an empty prompt store.

The VLM is always an ``AsyncMock`` — we never hit the network. The
Refiner is a **real** Refiner built from an ``InMemoryRefineRuleStore``
so that behaviours like frontmatter strip are actually observed.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock

from job_store import (
    InMemoryPromptStore,
    InMemoryRefineRuleStore,
    seed_prompts,
    seed_refine_rules,
)
from refine import Refiner
from revdoc.generator import ReverseDocGenerator, RevdocResult


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def prompt_store():
    store = InMemoryPromptStore()
    await seed_prompts(store)
    return store


@pytest_asyncio.fixture
async def empty_prompt_store():
    return InMemoryPromptStore()


@pytest_asyncio.fixture
async def refiner():
    rule_store = InMemoryRefineRuleStore()
    await seed_refine_rules(rule_store)
    return await Refiner.from_store(rule_store)


# --------------------------------------------------------------------------- #
# Helpers — gate-passing / failing MD fixtures
# --------------------------------------------------------------------------- #


def _valid_md(pad_chars: int = 900) -> str:
    """Build a reverse-doc MD that passes every gate check (no frontmatter).

    The body is padded with Korean filler so that (a) total length >= 800
    and (b) the Refiner's validator (>=10% Hangul, >=1 newline, >=100 chars)
    passes post-refine.
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
    # Korean filler ensures we clear both the gate length (>=800) and the
    # Refiner validator's Korean-ratio threshold (>=10%).
    pad = ("한국어 본문 추가 설명입니다.\n" * 100)[:pad_chars]
    return head + pad


def _valid_md_with_frontmatter() -> str:
    """Valid MD prefixed with a YAML frontmatter block to be stripped."""
    frontmatter = "---\ntitle: 고객 등급\nauthor: forge\n---\n\n"
    return frontmatter + _valid_md(pad_chars=900)


def _invalid_md_missing_section() -> str:
    """Valid MD minus the ``## 처리흐름`` section (gate fails on sections)."""
    md = _valid_md(pad_chars=900)
    return md.replace(
        "## 처리흐름\n1. 입력 수신\n2. 규칙 평가\n3. 결과 반환\n\n", ""
    )


# --------------------------------------------------------------------------- #
# 1. Pass on first try
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generator_pass_first_try(prompt_store, refiner):
    vlm = AsyncMock()
    vlm.process_text = AsyncMock(return_value=_valid_md(pad_chars=900))
    gen = ReverseDocGenerator(vlm=vlm, prompt_store=prompt_store, refiner=refiner)

    result = await gen.generate(source_code="def f(): pass", file_name="f.py")

    assert isinstance(result, RevdocResult)
    assert result.attempts == 1
    assert result.gate["passed"] is True
    assert result.gate["reason"] is None
    assert result.refine_report is not None
    # Refiner was actually invoked — report carries all 6 stages.
    assert set(result.refine_report.keys()) == {
        "encoding",
        "newline",
        "special_char",
        "frontmatter",
        "codefence",
        "traceability",
    }
    assert result.prompt_version == "reverse_doc-v1"
    # VLM called exactly once.
    assert vlm.process_text.await_count == 1


# --------------------------------------------------------------------------- #
# 2. Retry then pass
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generator_retries_on_gate_fail_then_pass(prompt_store, refiner):
    vlm = AsyncMock()
    # Two bad, then a good one.
    vlm.process_text = AsyncMock(
        side_effect=[
            _invalid_md_missing_section(),
            _invalid_md_missing_section(),
            _valid_md(pad_chars=900),
        ]
    )
    gen = ReverseDocGenerator(
        vlm=vlm, prompt_store=prompt_store, refiner=refiner, max_retries=2,
    )

    result = await gen.generate(source_code="code", file_name="x.py")

    assert result.attempts == 3
    assert result.gate["passed"] is True
    assert result.refine_report is not None
    assert vlm.process_text.await_count == 3


# --------------------------------------------------------------------------- #
# 3. Retries exhausted
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generator_retries_exhausted(prompt_store, refiner):
    bad_md = _invalid_md_missing_section()
    vlm = AsyncMock()
    vlm.process_text = AsyncMock(return_value=bad_md)  # always fails gate
    gen = ReverseDocGenerator(
        vlm=vlm, prompt_store=prompt_store, refiner=refiner, max_retries=2,
    )

    result = await gen.generate(source_code="code", file_name="x.py")

    # max_retries=2 → 3 total attempts
    assert result.attempts == 3
    assert vlm.process_text.await_count == 3
    assert result.gate["passed"] is False
    # Reason must mention the sections failure.
    assert result.gate["reason"] is not None
    assert "missing" in result.gate["reason"]
    # Last generation returned verbatim (no Refine on failure).
    assert result.result_text == bad_md
    assert result.refine_report is None


# --------------------------------------------------------------------------- #
# 4. Feedback injected into retry prompt
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generator_injects_feedback_into_prompt(prompt_store, refiner):
    vlm = AsyncMock()
    vlm.process_text = AsyncMock(
        side_effect=[
            _invalid_md_missing_section(),  # fail → produce feedback
            _valid_md(pad_chars=900),       # pass on retry
        ]
    )
    gen = ReverseDocGenerator(
        vlm=vlm, prompt_store=prompt_store, refiner=refiner, max_retries=2,
    )

    result = await gen.generate(source_code="code", file_name="f.py")
    assert result.gate["passed"] is True
    assert vlm.process_text.await_count == 2

    # First call: base prompt only, no feedback header.
    first_call_kwargs = vlm.process_text.await_args_list[0].kwargs
    assert "재시도 피드백" not in first_call_kwargs["prompt"]

    # Second call: feedback header present and mentions the missing section.
    second_call_kwargs = vlm.process_text.await_args_list[1].kwargs
    assert "재시도 피드백" in second_call_kwargs["prompt"]
    # Gate's feedback on section-failure names the missing section.
    assert "처리흐름" in second_call_kwargs["prompt"]
    # Base prompt is retained (the header is appended, not replaced).
    assert second_call_kwargs["prompt"].startswith(
        first_call_kwargs["prompt"][:100]
    )


# --------------------------------------------------------------------------- #
# 5. Refiner strips frontmatter on pass
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generator_applies_refiner_on_pass(prompt_store, refiner):
    md_with_fm = _valid_md_with_frontmatter()
    assert md_with_fm.startswith("---\n")  # sanity

    vlm = AsyncMock()
    vlm.process_text = AsyncMock(return_value=md_with_fm)
    gen = ReverseDocGenerator(vlm=vlm, prompt_store=prompt_store, refiner=refiner)

    result = await gen.generate(source_code="code", file_name="f.py")

    assert result.gate["passed"] is True
    # Frontmatter stripped → result_text no longer begins with '---' and
    # no longer contains the frontmatter-specific keys.
    assert not result.result_text.startswith("---\n")
    assert "title: 고객 등급" not in result.result_text
    # Frontmatter stage reports it was applied.
    assert result.refine_report is not None
    assert result.refine_report["frontmatter"]["applied"] is True


# --------------------------------------------------------------------------- #
# 6. prompt_version carries store version
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generator_prompt_version_from_store(prompt_store, refiner):
    # Bump reverse_doc to v2.
    await prompt_store.create_version("reverse_doc", "# v2 prompt text\n")
    active = await prompt_store.get_active("reverse_doc")
    assert active["version"] == 2

    vlm = AsyncMock()
    vlm.process_text = AsyncMock(return_value=_valid_md(pad_chars=900))
    gen = ReverseDocGenerator(vlm=vlm, prompt_store=prompt_store, refiner=refiner)

    result = await gen.generate(source_code="code", file_name="f.py")
    assert result.prompt_version == "reverse_doc-v2"

    # And the v2 prompt text was what got sent.
    first_kwargs = vlm.process_text.await_args_list[0].kwargs
    assert first_kwargs["prompt"].startswith("# v2 prompt text")


# --------------------------------------------------------------------------- #
# 7. Model override propagates to VLMClient
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generator_uses_model_override(prompt_store, refiner):
    vlm = AsyncMock()
    vlm.process_text = AsyncMock(return_value=_valid_md(pad_chars=900))
    gen = ReverseDocGenerator(
        vlm=vlm, prompt_store=prompt_store, refiner=refiner,
        model="gpt-4o-mini",
    )

    await gen.generate(source_code="code", file_name="f.py")
    kwargs = vlm.process_text.await_args_list[0].kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    # Sanity: purpose still "reverse_doc".
    assert kwargs["purpose"] == "reverse_doc"


# --------------------------------------------------------------------------- #
# 8. LookupError when no active prompt in store
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generator_raises_when_no_active_prompt(empty_prompt_store, refiner):
    vlm = AsyncMock()
    vlm.process_text = AsyncMock(return_value="unused")
    gen = ReverseDocGenerator(
        vlm=vlm, prompt_store=empty_prompt_store, refiner=refiner,
    )

    with pytest.raises(LookupError, match="reverse_doc"):
        await gen.generate(source_code="code", file_name="f.py")

    # VLM was never called — we fail fast on missing prompt.
    assert vlm.process_text.await_count == 0

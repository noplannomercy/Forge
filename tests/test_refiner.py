"""Tests for :class:`refine.Refiner` facade (T4).

Covers:
* construction from an ``InMemoryRefineRuleStore`` (all 7 versions loaded)
* happy-path Korean markdown (all stages no-op, gate passes)
* bytes decode + literal-newline substitution + frontmatter strip in one pass
* per-stage version tracking when one stage is upserted (others unchanged)
* short-text gate failure
* report structure (exactly the 6 stage keys)
* text-is-str post-encoding contract
* store-config immutability (regression for shallow-copy bug)
* validator version tracked separately from stage versions
"""

import pytest
import pytest_asyncio

from job_store import InMemoryRefineRuleStore, seed_refine_rules
from refine import Refiner, RefineResult


# --------------------------------------------------------------------------- #
# Fixtures
#
# pytest-asyncio is in strict mode (no pytest config asks for auto mode), so
# async fixtures must be declared with ``@pytest_asyncio.fixture`` rather
# than ``@pytest.fixture`` — otherwise pytest emits a
# ``PytestRemovedIn9Warning`` / setup error.
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def seeded_store():
    store = InMemoryRefineRuleStore()
    await seed_refine_rules(store)
    return store


@pytest_asyncio.fixture
async def refiner(seeded_store):
    return await Refiner.from_store(seeded_store)


# --------------------------------------------------------------------------- #
# 1. Construction from a store
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refiner_from_store_loads_all_configs(refiner):
    # 6 stages + validator = 7 version entries
    assert set(refiner._versions.keys()) == {
        "encoding",
        "newline",
        "special_char",
        "frontmatter",
        "codefence",
        "traceability",
        "validator",
    }
    # After seed_refine_rules, every entry should be version 1
    for stage, version in refiner._versions.items():
        assert version == 1, f"stage {stage} expected version 1, got {version}"


# --------------------------------------------------------------------------- #
# 2. Happy path — Korean markdown, all stages no-op
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_happy_path_korean_md(refiner):
    # Plain Korean markdown:
    # - no YAML frontmatter delimiter at byte 0
    # - no literal "\\n" sequences (only real newlines)
    # - no ~, ·, ↔, fullwidth chars
    # - no fenced code blocks (and strip=False anyway)
    # - >= 100 chars, >= 10% Hangul, >= 1 newline
    text = (
        "# 문서 제목\n\n"
        "이것은 테스트 문서입니다.\n"
        "충분히 긴 본문을 포함하여 검증기를 통과해야 합니다.\n"
        "한국어 비율도 충분히 높아야 합니다.\n"
        "여러 줄의 본문이 포함되어 있습니다.\n"
        "문서의 길이는 검증기의 최소 기준을 넘어야 합니다.\n"
    )
    assert len(text) >= 100, "test text must clear validator.min_length"
    result = refiner.refine(text)
    assert isinstance(result, RefineResult)
    assert result.text == text, "all default stages should be no-op on clean Korean md"
    assert result.quality["gate"] == "pass"
    assert "reason" not in result.quality
    # Every stage emitted a report
    for stage in Refiner.STAGE_ORDER:
        assert stage in result.report
        assert result.report[stage]["applied"] is False


# --------------------------------------------------------------------------- #
# 3. CP949 bytes + literal \n + frontmatter (plan's exemplar test)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_cp949_bytes_with_literal_newlines(refiner):
    # Build enough Korean content to clear the validator thresholds after
    # frontmatter strip. The literal "\\n" (two-char sequence) must survive
    # the source encoding and be converted by the newline stage.
    body_ko = "한글 본문입니다.\\n두번째 줄." + " 추가 본문. " * 20
    raw = ("---\ntitle: test\n---\n" + body_ko).encode("cp949")

    result = refiner.refine(raw)

    # frontmatter stripped
    assert "title:" not in result.text
    # literal \n converted to a real newline somewhere in the body
    assert "\n두번째" in result.text
    # gate passes
    assert result.quality["gate"] == "pass", result.quality
    # encoding stage reports the source encoding used
    assert result.report["encoding"]["applied"] is True
    assert result.report["encoding"]["details"]["from"] in {
        "utf-8-sig",
        "utf-8",
        "cp949",
        "euc-kr",
    }
    # newline stage counted at least one substitution (the literal \n)
    assert result.report["newline"]["changes"] >= 1
    # frontmatter stage applied
    assert result.report["frontmatter"]["applied"] is True


# --------------------------------------------------------------------------- #
# 4. Versions bump independently when one stage is upserted
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_preserves_rule_versions(seeded_store):
    # Bump `newline` only
    await seeded_store.upsert(
        "newline", {"patterns": [r"\\n"], "replace_with": "\n"}
    )
    refiner = await Refiner.from_store(seeded_store)

    assert refiner._versions["newline"] == 2
    for stage in Refiner.STAGE_ORDER:
        if stage == "newline":
            continue
        assert refiner._versions[stage] == 1, (
            f"stage {stage} version should be unchanged"
        )
    assert refiner._versions["validator"] == 1


# --------------------------------------------------------------------------- #
# 5. Gate failure — text too short
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_fails_gate_short_text(refiner):
    result = refiner.refine("한\n")
    assert result.quality["gate"] == "fail"
    assert "reason" in result.quality
    assert "length" in result.quality["reason"]
    # Report still populated for all 6 stages — gate only blocks downstream
    assert set(result.report.keys()) == set(Refiner.STAGE_ORDER)


# --------------------------------------------------------------------------- #
# 6. Report has exactly 6 stage keys
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_report_has_all_stages(refiner):
    result = refiner.refine("한국어 문서 " * 30 + "\n")
    assert set(result.report.keys()) == set(Refiner.STAGE_ORDER)
    assert len(result.report) == 6


# --------------------------------------------------------------------------- #
# 7. Post-encoding contract: text is str
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_text_is_str_after_stages(refiner):
    raw = ("한국어 문서 본문 " * 30 + "\n").encode("utf-8")
    result = refiner.refine(raw)
    assert isinstance(result.text, str)


# --------------------------------------------------------------------------- #
# 8. Refiner must not mutate store-cached configs
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_does_not_mutate_store_configs(seeded_store):
    # Snapshot every active config before constructing the Refiner
    before: dict[str, dict] = {}
    for stage in Refiner.STAGE_ORDER:
        before[stage] = dict(await seeded_store.active(stage))
    before["validator"] = dict(await seeded_store.active("validator"))

    refiner = await Refiner.from_store(seeded_store)
    # Drive a full refine pass to exercise any late mutation paths
    refiner.refine("한국어 본문 " * 40 + "\n")

    # After use, every stored config must still carry its `version` key
    # (regression: popping version from a shared reference would remove it).
    for stage in Refiner.STAGE_ORDER + ("validator",):
        active = await seeded_store.active(stage)
        assert "version" in active, f"{stage}: version key was mutated away"
        assert active == before[stage], f"{stage}: config mutated by Refiner"


# --------------------------------------------------------------------------- #
# 9. Validator version tracked separately
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_refine_validator_version_tracked_separately(seeded_store):
    # Bump validator to v2; stages remain v1
    await seeded_store.upsert(
        "validator",
        {
            "require_utf8": True,
            "min_newlines": 1,
            "min_korean_ratio": 0.1,
            "min_length": 50,
        },
    )
    refiner = await Refiner.from_store(seeded_store)

    result = refiner.refine("한국어 본문 " * 20 + "\n")

    assert "validator" in result.rule_versions
    assert result.rule_versions["validator"] == 2
    # Stage versions still 1
    for stage in Refiner.STAGE_ORDER:
        assert result.rule_versions[stage] == 1
    # And validator key is distinct from the stage keys
    assert set(result.rule_versions.keys()) == set(Refiner.STAGE_ORDER) | {
        "validator"
    }

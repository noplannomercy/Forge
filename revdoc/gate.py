"""Gate for reverse-doc generation (REVDOC-05) — simplified 2026-04-24.

Validates the structural requirements of LLM-generated reverse-doc Markdown
output before accepting it. Checks two things in strict priority order:

1. **Required sections** — the 7 mandated headers must all be present,
   at any heading level (``##``, ``###``, …). The exact Korean header text
   must match (see :data:`REQUIRED_SECTIONS`).
2. **Minimum length** — total character count must be ≥ ``min_length``
   (default 500, matching ``reverse_doc.md`` constraint).

The gate short-circuits on the first failing check and returns a
:class:`GateVerdict` with a ``feedback`` string — an actionable,
Korean-language retry prompt hint that T9's generator will feed back
into the LLM on the next attempt.

``feedback`` is populated only on failure (``None`` on pass). ``details``
is populated progressively as checks run — callers should treat it as
"what we measured up to the point we stopped".

The gate is pure and synchronous. It does not touch the DB, the store,
or any Cortex/LightRAG machinery (cf. constraints C1/C6).

**Note** (simplification 2026-04-24): the previous traceability triangle
check (Rule/Condition/Evidence keyword regex) was removed. See
``docs/superpowers/specs/2026-04-24-revdoc-gate-simplification-design.md``
for rationale (regex-based traceability was a sham — real traceability
requires semantic verification, which we do not perform).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

REQUIRED_SECTIONS = [
    "업무목적",
    "처리흐름",
    "입력/출력",
    "규칙/예외",
    "근거",
    "추적성",
    "관련업무",
]


@dataclass
class GateVerdict:
    """Outcome of a :class:`RevdocGate` check.

    Attributes:
        passed: True iff every check was satisfied.
        details: Measurements collected up to the point the gate stopped.
            On pass, contains ``missing_sections`` (empty list) and
            ``length`` (int). On section failure: only ``missing_sections``.
            On length failure: both keys.
        reason: Short machine-oriented failure description, ``None`` on pass.
        feedback: Korean-language retry hint for the LLM, ``None`` on pass.
    """

    passed: bool
    details: dict = field(default_factory=dict)
    reason: str | None = None
    feedback: str | None = None


class RevdocGate:
    """Structural quality gate for reverse-doc MD output.

    The gate is stateless beyond its ``min_length`` configuration. A single
    instance may be reused across many :meth:`check` calls.
    """

    def __init__(self, min_length: int = 500):
        self.min_length = min_length

    def check(self, md: str) -> GateVerdict:
        """Evaluate ``md`` against the two structural checks.

        Returns a :class:`GateVerdict` with priority-ordered failure:
        sections > length. Never raises on empty input.
        """
        details: dict = {}

        # 1. Required sections — highest priority.
        missing: list[str] = []
        for section in REQUIRED_SECTIONS:
            pattern = rf"^#+\s*{re.escape(section)}"
            if not re.search(pattern, md, re.M):
                missing.append(section)
        details["missing_sections"] = missing
        if missing:
            return GateVerdict(
                passed=False,
                details=details,
                reason=f"sections missing: {missing}",
                feedback=(
                    f"출력에 다음 섹션이 누락되었다: {missing}. "
                    "정확한 헤더로 다시 생성하라."
                ),
            )

        # 2. Length.
        details["length"] = len(md)
        if len(md) < self.min_length:
            return GateVerdict(
                passed=False,
                details=details,
                reason=f"length {len(md)} < min {self.min_length}",
                feedback=(
                    f"본문이 짧다 ({len(md)}자). 각 섹션을 더 충분히 서술하라."
                ),
            )

        return GateVerdict(passed=True, details=details)

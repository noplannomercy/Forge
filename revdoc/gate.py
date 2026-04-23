"""Gate for reverse-doc generation (REVDOC-05).

Validates the structural requirements of LLM-generated reverse-doc Markdown
output before accepting it. Checks three things in strict priority order:

1. **Required sections** — the 7 mandated headers must all be present,
   at any heading level (``##``, ``###``, …). The exact Korean header text
   must match (see :data:`REQUIRED_SECTIONS`).
2. **Traceability triangle** — ``Rule:``, ``Condition:``, ``Evidence:``
   must all appear somewhere in the document. Both ASCII colon (``:``)
   and fullwidth colon (``：`` U+FF1A) are accepted because Korean input
   methods commonly produce the latter. Positional matching inside the
   추적성 section is intentionally NOT enforced — simple presence anywhere
   suffices (the plan does not require strict positional matching).
3. **Minimum length** — total character count must be ≥ ``min_length``
   (default 800, matching ``reverse_doc_v1.md`` constraint).

The gate short-circuits on the first failing check and returns a
:class:`GateVerdict` with a ``feedback`` string — an actionable,
Korean-language retry prompt hint that T9's generator will feed back
into the LLM on the next attempt.

``feedback`` is populated only on failure (``None`` on pass). ``details``
is populated progressively as checks run — callers should treat it as
"what we measured up to the point we stopped".

The gate is pure and synchronous. It does not touch the DB, the store,
or any Cortex/LightRAG machinery (cf. constraints C1/C6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Exact header text required by reverse_doc_v1.md. Order here is also
# the canonical display order but the gate does NOT enforce order —
# only presence. (Order enforcement would be brittle against harmless
# LLM reorderings that still satisfy the spec.)
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
            On pass, contains ``missing_sections`` (empty list),
            ``traceability`` (all True), and ``length`` (int).
            On fail, contains the measurements for checks that had run
            by the time the failing check fired; later checks are absent.
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

    # Tolerates both ASCII ':' and fullwidth '：' (U+FF1A) which Korean IMEs
    # frequently emit. ``\s*`` lets ``Rule :`` pass as well — the goal is to
    # catch the triangle, not to police whitespace.
    _RULE_RE = re.compile(r"Rule\s*[:：]")
    _COND_RE = re.compile(r"Condition\s*[:：]")
    _EVID_RE = re.compile(r"Evidence\s*[:：]")

    def __init__(self, min_length: int = 800):
        self.min_length = min_length

    def check(self, md: str) -> GateVerdict:
        """Evaluate ``md`` against the three structural checks.

        Returns a :class:`GateVerdict` with priority-ordered failure:
        sections > traceability > length. Never raises on empty input.
        """
        details: dict = {}

        # 1. Required sections — highest priority.
        missing: list[str] = []
        for section in REQUIRED_SECTIONS:
            # ``re.escape`` handles '/' in "입력/출력". Any heading depth
            # (``#``..``######``) is accepted via ``#+``.
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

        # 2. Traceability triangle.
        has_rule = bool(self._RULE_RE.search(md))
        has_cond = bool(self._COND_RE.search(md))
        has_evid = bool(self._EVID_RE.search(md))
        details["traceability"] = {
            "rule": has_rule,
            "condition": has_cond,
            "evidence": has_evid,
        }
        if not (has_rule and has_cond and has_evid):
            missing_pieces: list[str] = []
            if not has_rule:
                missing_pieces.append("Rule")
            if not has_cond:
                missing_pieces.append("Condition")
            if not has_evid:
                missing_pieces.append("Evidence")
            return GateVerdict(
                passed=False,
                details=details,
                reason=f"traceability triangle incomplete: missing {missing_pieces}",
                feedback=(
                    "추적성 섹션에 Rule/Condition/Evidence 세 항목 모두 필요. "
                    f"누락: {missing_pieces}."
                ),
            )

        # 3. Length.
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

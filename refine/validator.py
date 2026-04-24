"""Content quality gate for the refine pipeline (REFINE-04).

Runs after all six refine stages have completed. Verifies that the refined
markdown meets a minimum quality bar before being handed off to downstream
consumers (e.g. LightRAG ingest).

The validator is a pure synchronous class. It never touches the DB or the
store; it receives its config dict from the caller (typically
``RefineRuleStore.active("validator")`` or ``REFINE_RULE_DEFAULTS["validator"]``).

Config schema (see ``job_store.REFINE_RULE_DEFAULTS["validator"]``)::

    {
        "require_utf8": True,
        "min_newlines": 1,
        "min_korean_ratio": 0.1,
        "min_length": 100,
        # "version": int — ignored by Validator, used by Refiner for reporting.
    }

Behavior notes:
* ``require_utf8`` is effectively a no-op at this layer: by the time text
  reaches the validator it is already a Python ``str``, which means it has
  already decoded successfully. The ``utf8`` check is therefore always
  recorded as ``True``. The key exists so the Refiner can surface the
  intent in its report and future transport-level validators can honour it.
* On failure the validator short-circuits and returns the first failing
  reason. The evaluation order is newlines → korean_ratio → length.
* ``korean_ratio`` counts only Hangul Syllables (U+AC00–U+D7A3); Hanja
  (CJK Unified Ideographs) and Jamo blocks are intentionally excluded.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GateVerdict:
    """Outcome of a validator check.

    Attributes:
        passed: True iff every configured threshold was satisfied.
        checks: measured values for every check — always contains the keys
            ``utf8``, ``newlines``, ``korean_ratio``, ``length`` regardless
            of pass/fail.
        reason: short human-readable failure description, or ``None`` on pass.
    """

    passed: bool
    checks: dict
    reason: str | None = None


class Validator:
    """Content quality gate executed after all refine stages.

    The validator is deliberately minimal — it inspects the refined text and
    emits a :class:`GateVerdict`. It is the Refiner's responsibility to act
    on the verdict (e.g. mark the job as ``refine_failed``).
    """

    def __init__(self, config: dict):
        self.config = config

    def check(self, text: str) -> GateVerdict:
        """Evaluate ``text`` against the configured thresholds.

        Returns a :class:`GateVerdict` with a fully-populated ``checks`` dict.
        Never returns ``None``. Never raises on empty input (guarded by
        ``total = len(text) or 1`` for the ratio denominator).
        """
        checks: dict = {}
        c = self.config

        # UTF-8: arriving here as a ``str`` means decoding already succeeded.
        # Always True at this stage; see module docstring.
        checks["utf8"] = True

        # Newline count — count of literal '\n' characters.
        newlines = text.count("\n")
        checks["newlines"] = newlines

        # Korean ratio — Hangul Syllables block U+AC00–U+D7A3 only.
        hangul = sum(1 for ch in text if 0xAC00 <= ord(ch) <= 0xD7A3)
        total = len(text) or 1
        korean_ratio = hangul / total
        checks["korean_ratio"] = round(korean_ratio, 3)

        # Length in characters.
        checks["length"] = len(text)

        # Judgement — order matters; return on first failure.
        if newlines < c["min_newlines"]:
            return GateVerdict(
                False,
                checks,
                f"newlines {newlines} < min {c['min_newlines']}",
            )
        if korean_ratio < c["min_korean_ratio"]:
            return GateVerdict(
                False,
                checks,
                f"korean_ratio {korean_ratio:.2f} < min {c['min_korean_ratio']}",
            )
        if len(text) < c["min_length"]:
            return GateVerdict(
                False,
                checks,
                f"length {len(text)} < min {c['min_length']}",
            )
        return GateVerdict(True, checks)

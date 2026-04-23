"""Refiner orchestrator — runs 6 stages sequentially then Validator gate.

The :class:`Refiner` ties together:

* the 6 refine stages in ``refine.stages.*`` (encoding → newline →
  special_char → frontmatter → codefence → traceability);
* the :class:`~refine.validator.Validator` quality gate.

Rule configs are supplied by a :class:`job_store.RefineRuleStore` (async).
``refine()`` itself is synchronous — only :meth:`Refiner.from_store` touches
the store.

Design notes:

* ``STAGE_ORDER`` is canonical. Stages are executed in this exact order.
* Store entries arrive with a ``version`` key (injected by
  ``RefineRuleStore.active()``). Versions are tracked separately by the
  Refiner (for traceability in :attr:`RefineResult.rule_versions`) and
  stripped before the config dict is handed to the stage constructor —
  stages do not know or care about versioning.
* Configs are shallow-copied before mutation to protect store state
  (prevents a regression where popping ``version`` would leak into the
  store's cached entry).
* ``EncodingStage`` may raise ``ValueError`` on undecodable bytes. That
  exception is allowed to propagate so callers can distinguish an encoding
  failure from a gate-fail refinement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .stages.codefence import CodefenceStage
from .stages.encoding import EncodingStage
from .stages.frontmatter import FrontmatterStage
from .stages.newline import NewlineStage
from .stages.special_char import SpecialCharStage
from .stages.traceability import TraceabilityStage
from .validator import GateVerdict, Validator


@dataclass
class RefineResult:
    """Outcome of a full :meth:`Refiner.refine` pass.

    Attributes:
        text: final refined string (always ``str``).
        report: ``{stage_name: StageReport-as-dict}`` — one entry per stage.
        quality: ``{"gate": "pass"|"fail", "checks": {...}, "reason": str}``
            where ``reason`` is only present on failure.
        rule_versions: ``{stage_name_or_"validator": version}`` — 7 entries
            for downstream traceability.
    """

    text: str
    report: dict[str, dict]
    quality: dict[str, Any]
    rule_versions: dict[str, int]


class Refiner:
    """Orchestrates 6 refine stages then the Validator gate."""

    STAGE_ORDER: tuple[str, ...] = (
        "encoding",
        "newline",
        "special_char",
        "frontmatter",
        "codefence",
        "traceability",
    )

    _STAGE_CLASSES: dict[str, type] = {
        "encoding": EncodingStage,
        "newline": NewlineStage,
        "special_char": SpecialCharStage,
        "frontmatter": FrontmatterStage,
        "codefence": CodefenceStage,
        "traceability": TraceabilityStage,
    }

    @classmethod
    async def from_store(cls, store) -> "Refiner":
        """Load all stage configs + validator config from a ``RefineRuleStore``.

        Calls ``store.active(stage)`` for each of the six stages and for the
        ``"validator"`` entry, then builds the Refiner synchronously.
        """
        configs: dict[str, dict] = {}
        for stage in cls.STAGE_ORDER:
            configs[stage] = await store.active(stage)
        configs["validator"] = await store.active("validator")
        return cls(configs)

    def __init__(self, configs: dict[str, dict]):
        self._stages: list[Any] = []
        self._versions: dict[str, int] = {}

        for stage_name in self.STAGE_ORDER:
            # Shallow copy so popping ``version`` cannot leak into the
            # store's cached dict (store entries are reused across calls).
            cfg = dict(configs[stage_name])
            version = cfg.pop("version", 1)
            self._versions[stage_name] = version
            self._stages.append(self._STAGE_CLASSES[stage_name](cfg))

        validator_cfg = dict(configs["validator"])
        self._versions["validator"] = validator_cfg.pop("version", 1)
        self._validator = Validator(validator_cfg)

    def refine(self, raw: bytes | str) -> RefineResult:
        """Run all 6 stages in order, then the validator.

        ``raw`` may be bytes (EncodingStage will decode) or str (EncodingStage
        is a pass-through). A decode failure in EncodingStage propagates as
        ``ValueError`` to the caller.
        """
        text: str | bytes = raw
        report: dict[str, dict] = {}

        for stage in self._stages:
            text, sr = stage.apply(text)
            report[sr.stage] = {
                "stage": sr.stage,
                "applied": sr.applied,
                "changes": sr.changes,
                "details": sr.details,
            }

        # Contract: after EncodingStage (first stage) text is always str.
        assert isinstance(text, str), (
            "Refiner contract violated: text must be str after stages"
        )

        verdict: GateVerdict = self._validator.check(text)
        quality: dict[str, Any] = {
            "gate": "pass" if verdict.passed else "fail",
            "checks": verdict.checks,
        }
        if verdict.reason:
            quality["reason"] = verdict.reason

        return RefineResult(
            text=text,
            report=report,
            quality=quality,
            rule_versions=dict(self._versions),
        )


__all__ = ["Refiner", "RefineResult"]

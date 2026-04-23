"""Refine stage interfaces.

Each stage is a tiny class with:
- `__init__(self, config: dict)` — config dict from `RefineRuleStore.active(stage)`.
  The dict may include a `version` key which stages ignore.
- `apply(self, text) -> tuple[str, StageReport]` — pure transform + report.

Stages never touch the DB, the store, or each other. The Refiner (T4) is
responsible for fetching config and chaining stages.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class StageReport:
    """Structured report emitted by each stage.

    Attributes:
        stage: stage name (e.g. "encoding", "newline").
        applied: whether the stage actually made a change.
        changes: number of replacements / edits performed.
        details: stage-specific diagnostic info (e.g. {"from": "cp949"}).
    """

    stage: str
    applied: bool
    changes: int
    details: dict


class Stage(Protocol):
    """Structural type for refine stages."""

    def apply(self, text: str | bytes) -> tuple[str, StageReport]: ...

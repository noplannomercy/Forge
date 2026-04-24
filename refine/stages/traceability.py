"""Traceability stage — regex-based rewrite for relation markers.

Default config rewrites `A ↔ B` into `A은 B에 연결된다.` so downstream
LightRAG extraction can pick up directional relations from flat text.
"""

from __future__ import annotations

import re

from refine.stages import StageReport


class TraceabilityStage:
    def __init__(self, config: dict):
        self.pattern: re.Pattern[str] = re.compile(config["pattern"])
        self.replace: str = config["replace"]

    def apply(self, text: str) -> tuple[str, StageReport]:
        new_text, n = self.pattern.subn(self.replace, text)
        return new_text, StageReport("traceability", n > 0, n, {})

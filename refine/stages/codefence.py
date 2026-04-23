"""Codefence stage — optionally remove fenced code blocks (```...```).

When `strip=False` (default), the stage is a pass-through so downstream
consumers still see code blocks. The Refiner decides per-deployment.
"""

from __future__ import annotations

import re

from refine.stages import StageReport


class CodefenceStage:
    # `[^\n]*` captures an optional language tag on the opening fence line
    # (e.g. ```python); `.*?` with DOTALL then captures the multiline body
    # up to the closing fence.
    _PATTERN = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)

    def __init__(self, config: dict):
        self.strip: bool = config.get("strip", False)

    def apply(self, text: str) -> tuple[str, StageReport]:
        if not self.strip:
            return text, StageReport("codefence", False, 0, {"reason": "strip=false"})
        new_text, n = self._PATTERN.subn("", text)
        return new_text, StageReport("codefence", n > 0, n, {})

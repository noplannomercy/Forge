"""Newline stage — substitute patterns (e.g. literal `\\n`) with real newlines."""

from __future__ import annotations

import re

from refine.stages import StageReport


class NewlineStage:
    def __init__(self, config: dict):
        self.patterns: list[re.Pattern[str]] = [re.compile(p) for p in config["patterns"]]
        self.replace_with: str = config["replace_with"]

    def apply(self, text: str) -> tuple[str, StageReport]:
        count = 0
        for p in self.patterns:
            text, n = p.subn(self.replace_with, text)
            count += n
        return text, StageReport("newline", count > 0, count, {})

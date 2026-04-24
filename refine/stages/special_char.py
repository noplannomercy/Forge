"""Special-char stage — literal replacements + optional NFKC width normalization.

The `replacements` count is the pre-replace occurrence count of each `src`
summed across the mapping. This is cleaner than the plan's post-hoc
`(len(old) - len(new.replace(dst, src))) // len(src)` formula, which breaks
when `dst` is a substring of `src` or vice versa. The observable contract
(StageReport.changes reflects edits made) is preserved.
"""

from __future__ import annotations

import unicodedata

from refine.stages import StageReport


class SpecialCharStage:
    def __init__(self, config: dict):
        self.mapping: dict[str, str] = config.get("map", {})
        self.normalize_width: bool = config.get("normalize_width", False)

    def apply(self, text: str) -> tuple[str, StageReport]:
        replacements = 0
        for src, dst in self.mapping.items():
            if not src:
                # guard against empty-key configs that would otherwise count
                # len(text)+1 occurrences of the empty string
                continue
            before_count = text.count(src)
            if before_count:
                text = text.replace(src, dst)
                replacements += before_count
        if self.normalize_width:
            text = unicodedata.normalize("NFKC", text)
        return text, StageReport("special_char", replacements > 0, replacements, {})

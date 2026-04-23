"""Frontmatter stage — strip YAML/TOML frontmatter block when present.

If the text begins with a delimiter line (e.g. `---`), everything up to and
including the next delimiter line is removed. If no matching closing delimiter
is found, the text is left untouched.

`keep_keys` is reserved for a future pass (preserving named keys as comments);
T2 treats it as a no-op parameter so a non-empty config value still parses.
"""

from __future__ import annotations

from refine.stages import StageReport


class FrontmatterStage:
    def __init__(self, config: dict):
        self.delimiters: list[str] = config.get("delimiters", ["---"])
        self.keep_keys: set[str] = set(config.get("keep_keys", []))

    def apply(self, text: str) -> tuple[str, StageReport]:
        for d in self.delimiters:
            if text.lstrip().startswith(d):
                end = text.find(f"\n{d}", len(d))
                if end > 0:
                    stripped = text[end + len(d) + 1:].lstrip("\n")
                    return stripped, StageReport(
                        "frontmatter",
                        True,
                        text[:end].count("\n"),
                        {"delimiter": d},
                    )
        return text, StageReport("frontmatter", False, 0, {})

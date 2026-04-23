"""Encoding stage — decode bytes to str using a try_order list.

If the input is already a str, the stage is a pass-through.
"""

from __future__ import annotations

from refine.stages import StageReport


class EncodingStage:
    def __init__(self, config: dict):
        self.try_order: list[str] = config["try_order"]

    def apply(self, raw: bytes | str) -> tuple[str, StageReport]:
        if isinstance(raw, str):
            return raw, StageReport("encoding", False, 0, {"reason": "already str"})
        for enc in self.try_order:
            try:
                text = raw.decode(enc)
                return text, StageReport("encoding", True, 0, {"from": enc})
            except UnicodeDecodeError:
                continue
        raise ValueError(f"decode failed (tried {self.try_order})")

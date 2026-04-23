"""Unit tests for refine/stages/*.

Stages are synchronous pure transforms — no async, no store. Where practical
we pull defaults from `REFINE_RULE_DEFAULTS` so tests stay aligned with the
seeded production configs.
"""

from __future__ import annotations

import pytest

from job_store import REFINE_RULE_DEFAULTS
from refine.stages import StageReport
from refine.stages.codefence import CodefenceStage
from refine.stages.encoding import EncodingStage
from refine.stages.frontmatter import FrontmatterStage
from refine.stages.newline import NewlineStage
from refine.stages.special_char import SpecialCharStage
from refine.stages.traceability import TraceabilityStage


# ---------------------------------------------------------------------------
# encoding
# ---------------------------------------------------------------------------

def test_encoding_cp949_to_utf8():
    stage = EncodingStage({"try_order": ["utf-8", "cp949"]})
    raw = "한글 테스트".encode("cp949")
    text, report = stage.apply(raw)
    assert text == "한글 테스트"
    assert isinstance(report, StageReport)
    assert report.stage == "encoding"
    assert report.applied is True
    # Successful bytes→str transformation counts as a change so downstream
    # aggregators that sum `r.changes` can detect the encoding pass.
    assert report.changes == 1
    assert report.details["from"] == "cp949"


def test_encoding_passes_through_already_str():
    stage = EncodingStage(REFINE_RULE_DEFAULTS["encoding"])
    text, report = stage.apply("이미 문자열")
    assert text == "이미 문자열"
    assert report.applied is False
    assert report.changes == 0
    assert report.details["reason"] == "already str"


def test_encoding_fails_when_all_decoders_fail():
    # Invalid UTF-8 and invalid cp949 — 0xff 0xfe is not a valid start byte
    # for either. Limiting try_order keeps the error path reachable.
    stage = EncodingStage({"try_order": ["utf-8", "ascii"]})
    with pytest.raises(ValueError, match="decode failed"):
        stage.apply(b"\xff\xfe\xfd\xfc")


def test_encoding_prefers_first_successful_decoder():
    stage = EncodingStage({"try_order": ["utf-8", "cp949"]})
    raw = "hello".encode("utf-8")
    _, report = stage.apply(raw)
    assert report.details["from"] == "utf-8"


# ---------------------------------------------------------------------------
# newline
# ---------------------------------------------------------------------------

def test_newline_literal_to_real():
    stage = NewlineStage(REFINE_RULE_DEFAULTS["newline"])
    text, report = stage.apply(r"a\nb\nc")
    assert text == "a\nb\nc"
    assert report.applied is True
    assert report.changes == 2
    assert report.stage == "newline"


def test_newline_no_change_when_clean():
    stage = NewlineStage(REFINE_RULE_DEFAULTS["newline"])
    text, report = stage.apply("a\nb\nc")
    assert text == "a\nb\nc"
    assert report.applied is False
    assert report.changes == 0


def test_newline_mixed_crlf_and_lf_patterns():
    # Longer pattern first so r"\r\n" is consumed before the bare r"\n".
    stage = NewlineStage({"patterns": [r"\\r\\n", r"\\n"], "replace_with": "\n"})
    text, report = stage.apply(r"line1\r\nline2\nline3")
    assert text == "line1\nline2\nline3"
    assert report.changes == 2


def test_newline_default_config_handles_crlf_without_dangling_cr():
    # Regression: the default `patterns` list must place r"\r\n" before r"\n"
    # so the shorter pattern does not consume the `\n` half of a CRLF pair
    # and leave a stray `\r` behind.
    stage = NewlineStage(REFINE_RULE_DEFAULTS["newline"])
    text, report = stage.apply(r"line1\r\nline2\r\nline3")
    assert "\r" not in text
    assert text == "line1\nline2\nline3"
    assert report.changes == 2


# ---------------------------------------------------------------------------
# special_char
# ---------------------------------------------------------------------------

def test_special_char_tilde_to_math_similar():
    stage = SpecialCharStage({"map": {"~": "∼"}, "normalize_width": False})
    text, report = stage.apply("a~b~c")
    assert text == "a∼b∼c"
    assert report.applied is True
    assert report.changes == 2


def test_special_char_normalize_width_nfkc():
    # Full-width "ABC" NFKC-normalizes to ASCII "ABC"
    stage = SpecialCharStage({"map": {}, "normalize_width": True})
    text, report = stage.apply("ＡＢＣ")
    assert text == "ABC"
    # changes count only reflects dict replacements, not NFKC width folding
    assert report.changes == 0


def test_special_char_no_change_when_empty_map():
    stage = SpecialCharStage({"map": {}, "normalize_width": False})
    text, report = stage.apply("unchanged")
    assert text == "unchanged"
    assert report.applied is False
    assert report.changes == 0


def test_special_char_skips_empty_src_key():
    # Empty-string key must not be treated as "match everywhere".
    stage = SpecialCharStage({"map": {"": "X"}, "normalize_width": False})
    text, report = stage.apply("abc")
    assert text == "abc"
    assert report.changes == 0


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------

def test_frontmatter_strips_yaml_block():
    stage = FrontmatterStage(REFINE_RULE_DEFAULTS["frontmatter"])
    doc = "---\ntitle: demo\nauthor: me\n---\n# Body\ncontent"
    text, report = stage.apply(doc)
    assert text == "# Body\ncontent"
    assert report.applied is True
    assert report.details["delimiter"] == "---"
    assert report.changes > 0


def test_frontmatter_no_change_when_no_delimiter():
    stage = FrontmatterStage(REFINE_RULE_DEFAULTS["frontmatter"])
    doc = "# Just a heading\nno frontmatter here"
    text, report = stage.apply(doc)
    assert text == doc
    assert report.applied is False
    assert report.changes == 0


def test_frontmatter_ignores_delimiter_mid_document():
    stage = FrontmatterStage(REFINE_RULE_DEFAULTS["frontmatter"])
    # Delimiter appears mid-doc, not at the start — must be left alone.
    doc = "intro text\n---\nkey: value\n---\nmore"
    text, report = stage.apply(doc)
    assert text == doc
    assert report.applied is False


def test_frontmatter_supports_alternate_delimiter():
    stage = FrontmatterStage({"delimiters": ["+++"], "keep_keys": []})
    doc = "+++\ntitle = \"demo\"\n+++\n# Body"
    text, report = stage.apply(doc)
    assert text == "# Body"
    assert report.applied is True
    assert report.details["delimiter"] == "+++"


def test_frontmatter_strict_start_leaves_leading_whitespace_untouched():
    # YAML/TOML frontmatter must start at byte 0 — leading whitespace means
    # this is not a valid frontmatter block and the text is returned unchanged.
    # (Historically this path called `text.lstrip().startswith(d)` which
    # silently mismatched the `find()` offset, corrupting output.)
    stage = FrontmatterStage(REFINE_RULE_DEFAULTS["frontmatter"])
    doc = "  \n---\nkey: value\n---\nbody"
    text, report = stage.apply(doc)
    assert text == doc
    assert report.applied is False
    assert report.changes == 0


# ---------------------------------------------------------------------------
# codefence
# ---------------------------------------------------------------------------

def test_codefence_no_change_when_strip_false():
    stage = CodefenceStage(REFINE_RULE_DEFAULTS["codefence"])  # strip=False default
    doc = "prefix\n```python\nprint('x')\n```\nsuffix"
    text, report = stage.apply(doc)
    assert text == doc
    assert report.applied is False
    assert report.details["reason"] == "strip=false"


def test_codefence_strips_fenced_blocks_when_enabled():
    stage = CodefenceStage({"strip": True})
    doc = "keep this\n```python\nprint('x')\n```\nand this"
    text, report = stage.apply(doc)
    assert "```" not in text
    assert "keep this" in text
    assert "and this" in text
    assert report.applied is True
    assert report.changes == 1


def test_codefence_preserves_surrounding_text():
    stage = CodefenceStage({"strip": True})
    doc = "before\n```\nfenced\n```\nafter\n```js\nmore\n```\nend"
    text, report = stage.apply(doc)
    assert "before" in text
    assert "after" in text
    assert "end" in text
    assert "fenced" not in text
    assert "more" not in text
    assert report.changes == 2


# ---------------------------------------------------------------------------
# traceability
# ---------------------------------------------------------------------------

def test_traceability_default_bidirectional_arrow():
    stage = TraceabilityStage(REFINE_RULE_DEFAULTS["traceability"])
    text, report = stage.apply("Alpha ↔ Beta")
    assert text == "Alpha은 Beta에 연결된다."
    assert report.applied is True
    assert report.changes == 1


def test_traceability_no_change_when_no_match():
    stage = TraceabilityStage(REFINE_RULE_DEFAULTS["traceability"])
    text, report = stage.apply("no arrows here")
    assert text == "no arrows here"
    assert report.applied is False
    assert report.changes == 0


def test_traceability_multiple_matches():
    stage = TraceabilityStage(REFINE_RULE_DEFAULTS["traceability"])
    text, report = stage.apply("A ↔ B\nC ↔ D")
    assert "A은 B에 연결된다." in text
    assert "C은 D에 연결된다." in text
    assert report.changes == 2

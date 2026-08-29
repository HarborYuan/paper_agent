"""Tests for the compact paper views, mainly the tl;dr extraction."""
from src.services.paper_views import summary_tldr

STRUCTURED = (
    "## TL;DR\nA streaming distillation framework that extends context 2-10x.\n\n"
    "## Problem\nStudent-teacher mismatch in streaming video generation.\n"
)
LEGACY = "## Problem\nSolves X.\n\n## Method Summary\nDoes Y with Z.\n"


def test_tldr_section_extracted():
    assert summary_tldr(STRUCTURED) == "A streaming distillation framework that extends context 2-10x."


def test_tldr_section_never_leaks_headings():
    assert "##" not in summary_tldr(STRUCTURED, 20)


def test_legacy_summary_falls_back_to_stripped_text():
    assert summary_tldr(LEGACY).startswith("Solves X.")
    assert "##" not in summary_tldr(LEGACY)


def test_tldr_truncates_with_ellipsis():
    out = summary_tldr(STRUCTURED, 20)
    assert len(out) == 21 and out.endswith("…")


def test_tldr_variant_heading_and_empty():
    assert summary_tldr("## TLDR\nShort one.\n## Problem\nP.") == "Short one."
    assert summary_tldr(None) == ""
    assert summary_tldr("") == ""

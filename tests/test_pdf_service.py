"""Text extraction: arXiv HTML preferred, PDF fallback, and size guards."""
import asyncio

import pytest

import src.services.pdf_service as mod
from src.services.pdf_service import PDFService, _parse_html

ARTICLE = """
<html><head><style>.x{}</style></head><body>
<div id="header">Report GitHub Issue arXiv is now an independent nonprofit! Back to Abstract</div>
<div id="watermark-tr">arXiv:2605.29496v1 [cs.CL]</div>
<div class="ltx_page_content">
<article class="ltx_document">
<h1 class="ltx_title">A Very Real Paper</h1>
<div class="ltx_authors"><span class="ltx_personname">Ada Researcher</span></div>
<p>Abstract text with math <math alttext="x^2 + 1"><mi>garbage</mi></math> inline.</p>
<script>console.log("nope")</script>
<p>Body&nbsp;paragraph.</p>
</article></div></body></html>
"""


def test_html_extraction_drops_arxiv_chrome():
    text = _parse_html(ARTICLE)
    assert text.startswith("A Very Real Paper")
    assert "Report GitHub Issue" not in text
    assert "watermark" not in text.lower()


def test_html_extraction_keeps_latex_and_drops_mathml():
    text = _parse_html(ARTICLE)
    assert "$x^2 + 1$" in text
    assert "garbage" not in text


def test_html_extraction_skips_scripts_and_normalises_space():
    text = _parse_html(ARTICLE)
    assert "console.log" not in text
    assert " " not in text
    assert "Body paragraph." in text


def test_html_without_article_falls_back_to_whole_page():
    text = _parse_html("<html><body><p>Bare page text</p></body></html>")
    assert "Bare page text" in text


def test_text_is_capped(monkeypatch):
    monkeypatch.setattr(mod, "MAX_TEXT_CHARS", 50)
    long_html = "<article><p>" + ("z" * 500) + "</p></article>"
    assert len(_parse_html(long_html)) <= 50


class _FakeStream:
    def __init__(self, status, chunks, headers=None):
        self.status_code = status
        self._chunks = chunks
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c


class _FakeClient:
    def __init__(self, response):
        self._response = response

    def stream(self, method, url, **kwargs):
        return self._response


def test_download_rejects_oversized_content_length():
    svc = PDFService()
    resp = _FakeStream(200, [b"x"], headers={"content-length": str(200 * 1024 * 1024)})
    got = asyncio.run(svc._download(_FakeClient(resp), "http://x/y.pdf", 30 * 1024 * 1024))
    assert got is None


def test_download_aborts_when_body_exceeds_cap_midstream():
    svc = PDFService()
    resp = _FakeStream(200, [b"a" * 40, b"b" * 40])
    got = asyncio.run(svc._download(_FakeClient(resp), "http://x/y.pdf", 50))
    assert got is None


def test_download_returns_body_within_cap():
    svc = PDFService()
    resp = _FakeStream(200, [b"ab", b"cd"])
    got = asyncio.run(svc._download(_FakeClient(resp), "http://x/y.pdf", 50))
    assert got == b"abcd"


def test_download_returns_none_on_error_status():
    svc = PDFService()
    got = asyncio.run(svc._download(_FakeClient(_FakeStream(404, [])), "http://x/y", 50))
    assert got is None


@pytest.mark.parametrize("url,expected", [
    ("https://arxiv.org/pdf/2605.29496v1", "2605.29496"),
    ("https://arxiv.org/abs/2510.12225", "2510.12225"),
    ("https://example.com/paper.pdf", None),
])
def test_arxiv_id_detection(url, expected):
    m = mod.ARXIV_ID_RE.search(url)
    assert (m.group(1) if m else None) == expected

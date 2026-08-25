"""Fetch a paper's full text.

arXiv has served LaTeXML-generated HTML for nearly every submission since late
2023, and it beats the PDF on every axis that matters here: the text comes out
in reading order instead of interleaved columns, equations carry their LaTeX in
`alttext`, and the download is a fraction of the size. So try HTML first and
keep the PDF as a fallback for the papers that have none.

The PDF path is deliberately defensive. Image-heavy submissions can run to
~100 MB, and the previous implementation read the whole body into memory and
then parsed it synchronously on the event loop, which is a good way to stall
(or OOM) the container. Downloads are now streamed with a size cap and parsing
runs in a worker thread.
"""

import asyncio
import io
import re
from html.parser import HTMLParser
from typing import Optional

import httpx
from pypdf import PdfReader

ARXIV_ID_RE = re.compile(
    r"arxiv\.org/(?:pdf|abs|html)/"
    r"([0-9]{4}\.[0-9]{4,5}|[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7})"
)

MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_HTML_BYTES = 12 * 1024 * 1024
MAX_TEXT_CHARS = 300_000          # matches SUMMARY_FULL_TEXT_CHAR_LIMIT; no point keeping more
HTTP_TIMEOUT = 30.0

# LaTeXML leaves author-defined macros it cannot expand as literal text, and they
# land at the very top of the document — inside the 8000-char window stage-2 reads.
# Macro names are lower-case by convention, so stopping at the first upper-case
# letter keeps the content that follows: "\\titreAmelioration" -> "Amelioration".
_LEAKED_MACRO_RE = re.compile(r"\\[a-z@]+(?:\[[^\]]{0,60}\])?")

_SKIP_TAGS = {"script", "style", "noscript", "head", "svg"}
_BLOCK_TAGS = {"p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6",
               "li", "tr", "br", "table", "figure", "figcaption"}


class _HTMLTextExtractor(HTMLParser):
    """Collect readable text, substituting LaTeX for rendered MathML.

    LaTeXML wraps the paper in <article class="ltx_document">; everything before
    it is arXiv's own chrome ("Report GitHub Issue", licence banners, and so on).
    That chrome is only a few hundred characters, but stage-2 sees just the first
    8000, so letting it through would push the title and abstract out of view.
    """

    saw_article = False

    def __init__(self, gate_on_article: bool = True):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._math_depth = 0
        self._size = 0
        self._gate = gate_on_article
        self._article_depth = 0

    @property
    def _collecting(self) -> bool:
        return self._article_depth > 0 if self._gate else True

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            self._article_depth += 1
            self.saw_article = True
            return
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "math":
            # MathML renders as unreadable character soup; the LaTeX source is right here.
            alt = dict(attrs).get("alttext")
            if alt and self._collecting and self._math_depth == 0:
                self._emit(f" ${alt}$ ")
            self._math_depth += 1
            return
        if self._math_depth == 0 and self._collecting and tag in _BLOCK_TAGS:
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag == "article":
            self._article_depth = max(0, self._article_depth - 1)
        elif tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "math":
            self._math_depth = max(0, self._math_depth - 1)

    def handle_data(self, data):
        if self._skip_depth or self._math_depth or not self._collecting:
            return
        # Only body text is scrubbed; LaTeX we emit ourselves from alttext is left alone.
        self._emit(_LEAKED_MACRO_RE.sub("", data))

    def _emit(self, s: str) -> None:
        if self._size >= MAX_TEXT_CHARS:
            return
        self._parts.append(s)
        self._size += len(s)

    @property
    def text(self) -> str:
        raw = "".join(self._parts)
        # LaTeXML indents generously; collapse runs of whitespace but keep paragraphs.
        raw = re.sub(r"[ \t\r\f\v\u00a0\u2009\u202f]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*", "\n\n", raw)
        return raw.replace("\ufeff", "").strip()[:MAX_TEXT_CHARS]


def _parse_html(markup: str) -> tuple[str, bool]:
    """Return (text, is_a_real_paper).

    The flag reports whether LaTeXML's <article> wrapper was present. Judging by
    length instead would throw away short papers: 2607.25928 is a genuine
    one-page proof whose HTML yields 2807 chars, and falling back to its PDF
    replaces clean "$\\#443$" with mangled "#443".
    """
    parser = _HTMLTextExtractor(gate_on_article=True)
    parser.feed(markup)
    parser.close()
    if parser.saw_article and parser.text:
        return parser.text, True
    # No <article> wrapper: an error page, or markup this parser does not understand.
    fallback = _HTMLTextExtractor(gate_on_article=False)
    fallback.feed(markup)
    fallback.close()
    return fallback.text, False


def _parse_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    out: list[str] = []
    size = 0
    for page in reader.pages:
        try:
            chunk = page.extract_text() or ""
        except Exception:
            continue
        out.append(chunk)
        size += len(chunk)
        if size >= MAX_TEXT_CHARS:
            break
    return "\n".join(out).strip()[:MAX_TEXT_CHARS]


class PDFService:
    def __init__(self):
        self.headers = {"User-Agent": "PaperAgent/1.0 (+https://arxiv.org)"}

    async def _download(self, client: httpx.AsyncClient, url: str, cap: int) -> Optional[bytes]:
        """Stream a response, abandoning anything larger than `cap`."""
        async with client.stream("GET", url, headers=self.headers, timeout=HTTP_TIMEOUT) as r:
            if r.status_code != 200:
                return None
            declared = r.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > cap:
                print(f"Skipping {url}: {int(declared) / 1e6:.0f}MB exceeds cap")
                return None
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > cap:
                    print(f"Skipping {url}: body exceeded {cap / 1e6:.0f}MB cap mid-download")
                    return None
            return bytes(buf)

    async def extract_text_from_url(self, pdf_url: str) -> Optional[str]:
        """Return the paper's text, preferring arXiv's HTML rendering."""
        match = ARXIV_ID_RE.search(pdf_url or "")
        arxiv_id = match.group(1) if match else None

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                if arxiv_id:
                    try:
                        body = await self._download(
                            client, f"https://arxiv.org/html/{arxiv_id}", MAX_HTML_BYTES)
                        if body:
                            text, is_paper = await asyncio.to_thread(
                                _parse_html, body.decode("utf-8", "replace"))
                            if is_paper and text:
                                print(f"Using arXiv HTML for {arxiv_id} ({len(text)} chars)")
                                return text
                    except Exception as e:
                        print(f"HTML fetch failed for {arxiv_id}, falling back to PDF: {e}")

                if not pdf_url:
                    return None
                print(f"Downloading PDF: {pdf_url}")
                body = await self._download(client, pdf_url, MAX_PDF_BYTES)
                if not body:
                    return None
                return await asyncio.to_thread(_parse_pdf, body)
        except Exception as e:
            print(f"Error extracting text from {pdf_url}: {e}")
            return None


pdf_service = PDFService()

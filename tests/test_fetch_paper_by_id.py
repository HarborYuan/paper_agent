"""
Tests for fetch_paper_by_id and authors_list robustness,
focusing on special characters in author names.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.services.arxiv import ArxivFetcher
from src.models import Paper


# ---------------------------------------------------------------------------
# Unit tests for Paper.authors_list (no network, no DB)
# ---------------------------------------------------------------------------

class TestAuthorsListParsing:
    """Test that authors_list handles various stored formats correctly."""

    def test_normal_json(self):
        p = Paper(
            id="0", title="T", summary_generic="S",
            authors='["Alice", "Bob"]',
            published_at=datetime.now(), category_primary="cs.CV",
            all_categories="[]", pdf_url=""
        )
        assert p.authors_list == ["Alice", "Bob"]

    def test_empty_string(self):
        p = Paper(
            id="0", title="T", summary_generic="S",
            authors="",
            published_at=datetime.now(), category_primary="cs.CV",
            all_categories="[]", pdf_url=""
        )
        assert p.authors_list == []

    def test_single_author(self):
        p = Paper(
            id="0", title="T", summary_generic="S",
            authors='["Alice"]',
            published_at=datetime.now(), category_primary="cs.CV",
            all_categories="[]", pdf_url=""
        )
        assert p.authors_list == ["Alice"]

    def test_author_with_apostrophe_valid_json(self):
        """json.dumps correctly encodes apostrophes — they're valid in JSON strings."""
        authors = ["Declan P. O'Regan", "Chen Qin"]
        p = Paper(
            id="0", title="T", summary_generic="S",
            authors=json.dumps(authors),
            published_at=datetime.now(), category_primary="cs.CV",
            all_categories="[]", pdf_url=""
        )
        assert p.authors_list == ["Declan P. O'Regan", "Chen Qin"]

    def test_author_with_special_chars(self):
        """Names with accents, hyphens, dots, etc."""
        authors = ["Jean-François Lalonde", "Marc-André Gardner", "José María"]
        p = Paper(
            id="0", title="T", summary_generic="S",
            authors=json.dumps(authors),
            published_at=datetime.now(), category_primary="cs.CV",
            all_categories="[]", pdf_url=""
        )
        assert p.authors_list == authors

    def test_author_with_html_entity(self):
        """arXiv sometimes returns &#39; for apostrophes."""
        authors = ["Declan P. O&#39;Regan"]
        p = Paper(
            id="0", title="T", summary_generic="S",
            authors=json.dumps(authors),
            published_at=datetime.now(), category_primary="cs.CV",
            all_categories="[]", pdf_url=""
        )
        assert p.authors_list == ["Declan P. O&#39;Regan"]

    def test_malformed_json_fallback(self):
        """Legacy data stored with str().replace("'",'"') that broke on apostrophes."""
        # This is what the OLD code produced for O'Regan:
        malformed = '["Siyi Du", "Xinzhe Luo", "Declan P. O"Regan", "Chen Qin"]'
        p = Paper(
            id="0", title="T", summary_generic="S",
            authors=malformed,
            published_at=datetime.now(), category_primary="cs.CV",
            all_categories="[]", pdf_url=""
        )
        result = p.authors_list
        # Fallback should still extract author names reasonably
        assert len(result) == 4
        assert "Siyi Du" in result
        assert "Chen Qin" in result


# ---------------------------------------------------------------------------
# Integration test: fetch_paper_by_id with a real arXiv paper (network call)
# ---------------------------------------------------------------------------

ARXIV_HTML_2601_22853 = """
<html>
<head><title>arXiv:2601.22853</title></head>
<body>
<h1 class="title mathjax"><span class="descriptor">Title:</span> Inference-Time Dynamic Modality Selection</h1>
<blockquote class="abstract mathjax">
  <span class="descriptor">Abstract:</span> Some abstract text here.
</blockquote>
<div class="authors"><span class="descriptor">Authors:</span>
  <a href="/search/?searchtype=au&query=Du">Siyi Du</a>,
  <a href="/search/?searchtype=au&query=Luo">Xinzhe Luo</a>,
  <a href="/search/?searchtype=au&query=O%27Regan">Declan P. O&#39;Regan</a>,
  <a href="/search/?searchtype=au&query=Qin">Chen Qin</a>
</div>
<td class="tablecell subjects">
  <span class="primary-subject">Computer Vision (cs.CV)</span>; Machine Learning (cs.LG)
</td>
<div class="submission-history">
  <strong>[v1]</strong> Mon, 27 Jan 2025 18:59:55 UTC (1,234 KB)
</div>
</body>
</html>
"""


class TestFetchPaperById:
    """Test fetch_paper_by_id with mocked HTTP responses."""

    def test_apostrophe_in_author_name(self):
        """The O'Regan case that originally caused the JSON crash."""
        fetcher = ArxivFetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ARXIV_HTML_2601_22853

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            papers = fetcher.fetch_paper_by_id("2601.22853")

        assert len(papers) == 1
        paper = papers[0]

        # The key assertion: authors must be valid JSON
        parsed = json.loads(paper.authors)
        assert isinstance(parsed, list)
        assert len(parsed) == 4

        # O'Regan should be stored correctly (with HTML entity from arXiv)
        assert any("Regan" in a for a in parsed)
        assert "Siyi Du" in parsed
        assert "Chen Qin" in parsed

        # authors_list property should also work
        assert paper.authors_list == parsed

    def test_normal_authors(self):
        """Simple author names without special characters."""
        html = """
        <html><body>
        <h1 class="title mathjax"><span class="descriptor">Title:</span> Test Paper</h1>
        <blockquote class="abstract mathjax"><span class="descriptor">Abstract:</span> Abstract.</blockquote>
        <div class="authors"><span class="descriptor">Authors:</span>
          <a href="#">Alice Smith</a>, <a href="#">Bob Jones</a>
        </div>
        <td class="tablecell subjects"><span class="primary-subject">AI (cs.AI)</span></td>
        <div class="submission-history">
          <strong>[v1]</strong> Mon, 01 Jan 2024 00:00:00 UTC (100 KB)
        </div>
        </body></html>
        """
        fetcher = ArxivFetcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            papers = fetcher.fetch_paper_by_id("2401.00001")

        assert len(papers) == 1
        assert json.loads(papers[0].authors) == ["Alice Smith", "Bob Jones"]

    def test_accented_author_names(self):
        """Authors with accented/unicode characters (common in academic names)."""
        html = """
        <html><body>
        <h1 class="title mathjax"><span class="descriptor">Title:</span> Test</h1>
        <blockquote class="abstract mathjax"><span class="descriptor">Abstract:</span> A.</blockquote>
        <div class="authors"><span class="descriptor">Authors:</span>
          <a href="#">Jean-François Lalonde</a>,
          <a href="#">Krešimir Romić</a>,
          <a href="#">José María López</a>
        </div>
        <td class="tablecell subjects"><span class="primary-subject">CV (cs.CV)</span></td>
        <div class="submission-history">
          <strong>[v1]</strong> Tue, 01 Jan 2024 00:00:00 UTC (50 KB)
        </div>
        </body></html>
        """
        fetcher = ArxivFetcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            papers = fetcher.fetch_paper_by_id("2401.00002")

        parsed = json.loads(papers[0].authors)
        assert "Jean-François Lalonde" in parsed
        assert "Krešimir Romić" in parsed
        assert "José María López" in parsed

    def test_404_returns_empty(self):
        """Non-existent paper should return empty list."""
        fetcher = ArxivFetcher()
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            papers = fetcher.fetch_paper_by_id("9999.99999")

        assert papers == []


# ---------------------------------------------------------------------------
# Integration test: /authors API with special character authors
# ---------------------------------------------------------------------------

class TestAuthorsAPIWithSpecialChars:
    """Test that the /authors API handles special-char author names end-to-end."""

    def test_apostrophe_author_in_api(self, client, session):
        """O'Regan-style names should work through the full API."""
        p = Paper(
            id="1", title="P1",
            authors=json.dumps(["Declan P. O'Regan", "Chen Qin"]),
            summary_generic="", published_at=datetime.now(),
            category_primary="cs.CV", all_categories='["cs.CV"]',
            pdf_url="", updated_at=datetime.now(), status="NEW"
        )
        session.add(p)
        session.commit()

        # GET /authors should include O'Regan
        resp = client.get("/authors")
        assert resp.status_code == 200
        data = resp.json()
        names = [d["name"] for d in data]
        assert "Declan P. O'Regan" in names
        assert "Chen Qin" in names

    def test_apostrophe_author_papers_endpoint(self, client, session):
        """GET /authors/{name}/papers should match O'Regan exactly."""
        p = Paper(
            id="1", title="P1",
            authors=json.dumps(["Declan P. O'Regan", "Alice"]),
            summary_generic="", published_at=datetime.now(),
            category_primary="cs.CV", all_categories='["cs.CV"]',
            pdf_url="", updated_at=datetime.now(), status="NEW"
        )
        session.add(p)
        session.commit()

        resp = client.get("/authors/Declan%20P.%20O%27Regan/papers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "1"

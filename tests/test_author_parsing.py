
import pytest
from unittest.mock import patch, MagicMock
from src.services.arxiv import ArxivFetcher

def test_author_parsing_cleaning():
    # Mock feedparser entry
    mock_entry = MagicMock()
    mock_entry.id = "http://arxiv.org/abs/2101.12345v1"
    mock_entry.title = "Test Title"
    mock_entry.summary = "Test Abstract"
    mock_entry.published_parsed = (2023, 1, 1, 0, 0, 0, 0, 0, 0)
    mock_entry.updated_parsed = (2023, 1, 1, 0, 0, 0, 0, 0, 0)
    mock_entry.arxiv_primary_category = {"term": "cs.AI"}
    mock_entry.tags = [{"term": "cs.AI"}]
    mock_entry.links = []

    # Case 1: Authors with colon and empty string resulting from split/bad data
    # Simulating what we saw: "Team Hunyuan3D", ":", "Bowen Zhang"
    # But feedparser gives a list of objects with .name attribute
    author1 = MagicMock(); author1.name = "Team Hunyuan3D"
    author2 = MagicMock(); author2.name = ":"  # This should be removed
    author3 = MagicMock(); author3.name = "Bowen Zhang"
    author4 = MagicMock(); author4.name = "Google Deepmind: John Smith" # Should become "Google Deepmind John Smith"

    mock_entry.authors = [author1, author2, author3, author4]

    mock_feed = MagicMock()
    mock_feed.entries = [mock_entry]

    with patch('feedparser.parse', return_value=mock_feed):
        fetcher = ArxivFetcher()
        papers = fetcher.fetch_papers(max_results=1)

    assert len(papers) == 1
    paper = papers[0]
    
    # We need to check paper.authors_list (which does json.loads)
    authors = paper.authors_list
    print(f"Parsed authors: {authors}")

    assert ":" not in authors
    assert "Team Hunyuan3D" in authors
    assert "Bowen Zhang" in authors
    assert "Google Deepmind John Smith" in authors # Colon removed inside name
    assert len(authors) == 3 # Should be 3 valid authors

if __name__ == "__main__":
    # fast way to run without full pytest setup if needed, but we'll use pytest
    try:
        test_author_parsing_cleaning()
        print("Test passed!")
    except AssertionError as e:
        print(f"Test failed: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")

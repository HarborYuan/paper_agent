import feedparser
import urllib.parse
from datetime import datetime
from typing import List
from sqlmodel import Session, select
from src.models import Paper
from src.database import engine

ARXIV_API_URL = "http://export.arxiv.org/api/query"

class ArxivFetcher:
    def __init__(self, categories: List[str] = ["cs.CV", "cs.CL", "cs.AI"]):
        self.categories = categories

    def fetch_papers(self, max_results: int = 2000) -> List[Paper]:
        """
        Fetch papers from arXiv API for the configured categories.
        Sort by submittedDate descending (newest first).
        """
        # Construct query: cat:cs.CV OR cat:cs.CL ...
        cat_query = " OR ".join([f"cat:{cat}" for cat in self.categories])
        
        # Determine strict date range?
        # For MVP, we just ask for the latest N papers and filter by DB existence.
        # "submittedDate" is the standard sort.
        
        query_params = {
            "search_query": cat_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": max_results,
        }
        
        url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(query_params)}"
        print(f"Fetching from arXiv: {url}")
        
        feed = feedparser.parse(url)
        
        papers = []
        for entry in feed.entries:
            # Extract ID: http://arxiv.org/abs/2101.12345v1 -> 2101.12345v1 or just 2101.12345
            # User typically wants versioned or unversioned. The atom ID is usually a URL.
            # We will use the ID string from the ID field.
            arxiv_id = entry.id.split("/abs/")[-1]
            
            # Helper to safely get attributes
            title = entry.title.replace("\n", " ")
            abstract = entry.summary.replace("\n", " ")
            authors = [author.name for author in entry.authors]
            published = datetime(*entry.published_parsed[:6])
            updated = datetime(*entry.updated_parsed[:6])
            
            # Primary category
            primary_cat = entry.arxiv_primary_category["term"]
            
            # All categories
            categories = [tag["term"] for tag in entry.tags]
            
            # PDF Link
            pdf_url = ""
            for link in entry.links:
                if link.type == "application/pdf":
                    pdf_url = link.href
            
            paper = Paper(
                id=arxiv_id,
                title=title,
                authors=str(authors).replace("'", '"'), # Simple JSON dump
                summary_generic=abstract,   
                published_at=published,
                category_primary=primary_cat,
                all_categories=str(categories).replace("'", '"'), # Simple JSON dump
                pdf_url=pdf_url,
                updated_at=updated
            )
            papers.append(paper)
            
        print(f"Fetched {len(papers)} entries from arXiv.")
        return papers

    def filter_new_papers(self, papers: List[Paper]) -> List[Paper]:
        """
        Check against DB to return only papers that do not exist.
        """
        new_papers = []
        # We can optimize this with a single query using IN, 
        # but for 100 papers a loop or chunked query is fine for MVP.
        # Better: select all IDs from DB that match these IDs.
        
        if not papers:
            return []
            
        paper_ids = [p.id for p in papers]
        
        with Session(engine) as session:
            statement = select(Paper.id).where(Paper.id.in_(paper_ids))
            existing_ids = session.exec(statement).all()
            existing_set = set(existing_ids)
            
        for p in papers:
            if p.id not in existing_set:
                new_papers.append(p)
                
        return new_papers

    def save_papers(self, papers: List[Paper]):
        if not papers:
            return
        
        with Session(engine) as session:
            for p in papers:
                session.add(p)
            session.commit()
            print(f"Saved {len(papers)} new papers to DB.")

def run_fetch_cycle():
    from src.config import settings
    fetcher = ArxivFetcher(categories=settings.ARXIV_CATEGORIES)
    fetched = fetcher.fetch_papers(max_results=2000)
    new_ones = fetcher.filter_new_papers(fetched)
    print(f"New papers after deduplication: {len(new_ones)}")
    fetcher.save_papers(new_ones)
    return new_ones

if __name__ == "__main__":
    # Test run
    # Ensure DB is created first
    from src.database import init_db
    try:
        init_db()
    except Exception as e:
        print(f"DB Init warning: {e}")
        
    run_fetch_cycle()

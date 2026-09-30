import feedparser
import httpx
import json
import re
import time
from datetime import datetime
from typing import Dict, List, Optional
from sqlmodel import Session, select
from src.models import Paper
from src.database import engine

ARXIV_API_URL = "https://export.arxiv.org/api/query"
API_TIMEOUT = 60.0
# Seconds to wait before each retry. arXiv asks for >= 3 s between calls; its API also has
# transient bad spells (5xx, empty feeds), so the daily fetch backs off generously.
RETRY_DELAYS = (5, 20, 60)
ID_LIST_CHUNK = 100


class ArxivAPIError(RuntimeError):
    """The arXiv export API failed (network / HTTP error, error feed, or an empty result) after retries."""


def _strip_version(arxiv_id: str) -> str:
    return re.sub(r'v\d+$', '', arxiv_id)


def query_api(params: Dict, *, require_entries: bool = True, retry_delays=None) -> feedparser.FeedParserDict:
    """
    GET the arXiv export API and parse the Atom feed, retrying transient failures.
    Raises ArxivAPIError when every attempt failed. `require_entries` treats an empty feed as a
    failure — right for the category listing (which is never legitimately empty), wrong for id lookups.
    """
    delays = RETRY_DELAYS if retry_delays is None else retry_delays
    last_error = "unknown error"
    for attempt in range(len(delays) + 1):
        if attempt:
            time.sleep(delays[attempt - 1])
        try:
            with httpx.Client(follow_redirects=True, timeout=API_TIMEOUT,
                              headers={"User-Agent": "paper-agent (https://github.com/HarborYuan/paper_agent)"}) as client:
                resp = client.get(ARXIV_API_URL, params=params)
        except httpx.HTTPError as e:
            last_error = f"{type(e).__name__}: {e}"
            print(f"arXiv API attempt {attempt + 1} failed: {last_error}")
            continue
        if resp.status_code != 200:
            last_error = f"HTTP {resp.status_code}: {resp.text[:200].strip()}"
            print(f"arXiv API attempt {attempt + 1} failed: {last_error}")
            continue
        feed = feedparser.parse(resp.text)
        # The API reports bad queries as a single entry whose id points at /api/errors
        errors = [e for e in feed.entries if "/api/errors" in e.get("id", "")]
        if errors:
            raise ArxivAPIError(f"arXiv API error: {errors[0].get('summary', errors[0].get('title', ''))}".strip())
        if feed.bozo and not feed.entries:
            last_error = f"unparseable feed: {feed.get('bozo_exception')}"
            print(f"arXiv API attempt {attempt + 1} failed: {last_error}")
            continue
        if require_entries and not feed.entries:
            last_error = "empty feed (0 entries)"
            print(f"arXiv API attempt {attempt + 1} failed: {last_error}")
            continue
        return feed
    raise ArxivAPIError(f"arXiv API failed after {len(delays) + 1} attempts: {last_error}")


def fetch_metadata(paper_ids: List[str], retry_delays=None) -> Dict[str, Dict]:
    """
    Title / authors / comment / journal_ref / dates for specific arXiv ids via the API (id_list),
    keyed by version-less id. Unknown ids are simply absent. Raises ArxivAPIError.
    """
    ids = list(dict.fromkeys(_strip_version(i) for i in paper_ids if i))
    out: Dict[str, Dict] = {}
    for n in range(0, len(ids), ID_LIST_CHUNK):
        if n:
            time.sleep(3)
        chunk = ids[n:n + ID_LIST_CHUNK]
        feed = query_api({"id_list": ",".join(chunk), "max_results": len(chunk)},
                         require_entries=False, retry_delays=retry_delays)
        for e in feed.entries:
            pid = _strip_version(e.id.split("/abs/")[-1])
            if pid not in chunk or not e.get("title"):
                continue
            out[pid] = {
                "id": pid,
                "title": " ".join(e.title.split()),
                "authors": [a.name.replace(":", "").strip() for a in e.get("authors", []) if a.get("name")],
                "comment": " ".join((e.get("arxiv_comment") or "").split()) or None,
                "journal_ref": " ".join((e.get("arxiv_journal_ref") or "").split()) or None,
                "doi": e.get("arxiv_doi"),
                "published": datetime(*e.published_parsed[:6]) if e.get("published_parsed") else None,
                "updated": datetime(*e.updated_parsed[:6]) if e.get("updated_parsed") else None,
            }
    return out


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
        
        print(f"Fetching from arXiv: {ARXIV_API_URL} {query_params}")
        # Raises ArxivAPIError if the API is down / returns nothing; run_worker alerts on it
        feed = query_api(query_params)
        
        papers = []
        for entry in feed.entries:
            # Extract ID: http://arxiv.org/abs/2101.12345v1 -> 2101.12345v1 or just 2101.12345
            # User typically wants versioned or unversioned. The atom ID is usually a URL.
            # We will use the ID string from the ID field.
            arxiv_id = _strip_version(entry.id.split("/abs/")[-1])
            
            # Helper to safely get attributes
            title = entry.title.replace("\n", " ")
            abstract = entry.summary.replace("\n", " ")
            authors = []
            for author in entry.authors:
                # Clean author name: remove colons and surrounding whitespace
                name = author.name.replace(":", "").strip()
                if name:
                    authors.append(name)
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
                authors=json.dumps(authors),
                summary_generic=abstract,   
                published_at=published,
                category_primary=primary_cat,
                all_categories=json.dumps(categories),
                pdf_url=pdf_url,
                updated_at=updated
            )
            papers.append(paper)
            
        print(f"Fetched {len(papers)} entries from arXiv.")
        return papers

    def fetch_paper_by_id(self, paper_id: str) -> List[Paper]:
        """
        Fetch a specific paper by its arXiv ID using web scraping to avoid API rate limits/instability.
        """
        import httpx
        import re
        
        url = f"https://arxiv.org/abs/{paper_id}"
        print(f"Fetching specific paper from arXiv (scraping): {url}")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        try:
            with httpx.Client(follow_redirects=True) as client:
                response = client.get(url, headers=headers)
                if response.status_code != 200:
                    print(f"Failed to fetch paper page: {response.status_code}")
                    return []
                html = response.text
        except Exception as e:
            print(f"Error scraping arXiv: {e}")
            return []
            
        # Parse HTML
        # 1. Title
        title_match = re.search(r'<h1 class="title mathjax"><span class="descriptor">Title:</span>\s*(.*?)</h1>', html, re.DOTALL)
        title = title_match.group(1).strip() if title_match else f"Paper {paper_id}"
        
        # 2. Abstract
        abs_match = re.search(r'<blockquote class="abstract mathjax">\s*<span class="descriptor">Abstract:</span>\s*(.*?)</blockquote>', html, re.DOTALL)
        abstract = abs_match.group(1).strip() if abs_match else ""
        
        # 3. Authors
        authors_div_match = re.search(r'<div class="authors"><span class="descriptor">Authors:</span>(.*?)(?:</div>)', html, re.DOTALL)
        authors_html = authors_div_match.group(1) if authors_div_match else ""
        authors = re.findall(r'<a href="[^"]+"[^>]*>(.*?)</a>', authors_html)
        
        # 4. Date and Submission History
        # Try to find the latest version timestamp in submission history
        # Pattern: <strong>[v1]</strong> Thu, 28 Dec 2023 14:13:35 UTC (18,539 KB)
        # We look for the last occurrence of such pattern or specific div
        # Using findall to get all versions (usually sorted) and take the last one or logic to find max version
        # Regex handles optional </strong> and whitespace
        submission_dates = re.findall(r'\[(v\d+)\](?:</strong>)?\s*(\w{3}, \d{1,2} \w{3} \d{4} \d{2}:\d{2}:\d{2} UTC)', html)
        
        published = datetime.now()
        
        if submission_dates:
            # submission_dates is list of tuples [('v1', 'Date...'), ('v2', 'Date...')]
            # We want the latest version. Assuming textual order (usually v1..vN)?
            # Or just take the last one found in the submission-history div?
            # It's safer to rely on the version number to sort.
            try:
                # Sort by version number
                latest = sorted(submission_dates, key=lambda x: int(x[0].replace('v', '')))[-1]
                date_str = latest[1]
                published = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z")
            except Exception as e:
                print(f"Error parsing submission history date: {e}")
                # Fallback to dateline if parsing fails
                date_match = re.search(r'<div class="dateline">\s*\[Submitted on\s+(.*?)\]', html, re.DOTALL)
                if date_match:
                    try:
                        published = datetime.strptime(date_match.group(1), "%d %b %Y")
                    except:
                        pass
        else:
             # Fallback
            date_match = re.search(r'<div class="dateline">\s*\[Submitted on\s+(.*?)\]', html, re.DOTALL)
            if date_match:
                try:
                    published = datetime.strptime(date_match.group(1), "%d %b %Y")
                except:
                    pass

        # 5. Categories (All)
        # <td class="tablecell subjects">
        # <span class="primary-subject">Computer Vision and Pattern Recognition (cs.CV)</span>; Artificial Intelligence (cs.AI); Machine Learning (cs.LG)</td>
        subjects_match = re.search(r'<td class="tablecell subjects">(.*?)</td>', html, re.DOTALL)
        categories = []
        primary_cat = "cs.AI"
        
        if subjects_match:
            subjects_text = subjects_match.group(1)
            # Remove HTML tags to get raw text like "Computer Vision... (cs.CV); Artificial... (cs.AI)"
            clean_text = re.sub(r'<[^>]+>', '', subjects_text).strip()
            # Split by semicolon
            parts = clean_text.split(';')
            for part in parts:
                # Extract code in parens (cs.XX)
                code_match = re.search(r'\((.*?)\)', part)
                if code_match:
                    code = code_match.group(1)
                    categories.append(code)
            
            # Identify primary
            # The primary subject is usually flagged with a span class="primary-subject" in the original HTML
            # We can extract it separately or just assume the first one if we can't find the span tag in the raw text regex above.
            # actually we stripped tags. Let's look at the original HTML snippet for primary.
            primary_match = re.search(r'<span class="primary-subject">.*?\((\w+\.\w+)\).*?</span>', subjects_text, re.DOTALL)
            if primary_match:
                primary_cat = primary_match.group(1)
            elif categories:
                primary_cat = categories[0]
        else:
            # Fallback to old method if table structure changes
            cat_match = re.search(r'<span class="primary-subject">(.*?)</span>', html)
            if cat_match:
                cat_full = cat_match.group(1)
                cat_code_match = re.search(r'\((.*?)\)', cat_full)
                if cat_code_match:
                    primary_cat = cat_code_match.group(1)
                    categories = [primary_cat]
        
        # 6. PDF
        pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"
        
        paper = Paper(
            id=paper_id,
            title=title,
            authors=json.dumps(authors),
            summary_generic=abstract,   
            published_at=published,
            category_primary=primary_cat,
            all_categories=json.dumps(categories),
            pdf_url=pdf_url,
            updated_at=datetime.now()
        )
        
        return [paper]

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

"""Backfill papers the daily fetch window missed.

The daily worker only grabs the newest N announced papers sorted by
submittedDate, so papers announced late (or submitted while the instance was
down) never enter the DB. This script walks a submittedDate range day by day,
diffs the arXiv listing against the DB, fetches metadata for the missing ids
in batches (arXiv API id_list, 100 per request), and inserts them through
POST /api/papers/bulk-insert. Nothing is pushed: papers land as NEW and the
scheduled run scores them in batch, so the digest stays the delivery channel.

Run inside the repo so feedparser is available:
    uv run python scripts/backfill_missing.py --from 2026-02-05 --to 2026-08-23 \
        [--base-url http://nas:8000] [--categories cs.CV,cs.CL] [--dry-run]

Resumable: finished days are recorded in the state file (--state,
default backfill_state.json next to this script); rerunning skips them.
After the backfill, trigger POST /api/embeddings/backfill once so the new
papers get vectors for semantic search.
"""

import argparse
import json
import re
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import feedparser

ARXIV_API = "https://export.arxiv.org/api/query"
UA = {"User-Agent": "paper-agent-backfill/1.0"}
PAGE_SIZE = 200
ID_BATCH = 100           # ids per id_list metadata request
ARXIV_PAUSE = 5          # seconds between arXiv API calls (their guidance is >= 3)
BACKOFF_START = 60       # seconds; doubled per retry up to BACKOFF_CAP
BACKOFF_CAP = 600
MAX_RETRIES = 8


def arxiv_get(url: str) -> str:
    backoff = BACKOFF_START
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=60).read().decode()
        except Exception as e:
            print(f"    arXiv error (attempt {attempt + 1}/{MAX_RETRIES}): {e}; backing off {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_CAP)
    raise RuntimeError(f"arXiv unreachable after {MAX_RETRIES} attempts: {url}")


def arxiv_ids_for_day(day: date, categories: list[str]) -> list[str]:
    d = day.strftime("%Y%m%d")
    cat_q = "+OR+".join(f"cat:{c}" for c in categories)
    ids: list[str] = []
    start = 0
    while True:
        url = (f"{ARXIV_API}?search_query=%28{cat_q}%29+AND+submittedDate:%5B{d}0000+TO+{d}2359%5D"
               f"&start={start}&max_results={PAGE_SIZE}")
        xml = arxiv_get(url)
        total_m = re.search(r"totalResults[^>]*>(\d+)<", xml)
        if not total_m:
            raise RuntimeError(f"Unparseable arXiv response for {day}")
        total = int(total_m.group(1))
        batch = re.findall(r"<id>https?://arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5})", xml)
        ids.extend(batch)
        start += PAGE_SIZE
        if start >= total or not batch:
            break
        time.sleep(ARXIV_PAUSE)
    seen: set[str] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


def fetch_metadata(ids: list[str]) -> list[dict]:
    """Fetch full metadata for the given ids via the API's id_list batching."""
    records: list[dict] = []
    for i in range(0, len(ids), ID_BATCH):
        chunk = ids[i:i + ID_BATCH]
        time.sleep(ARXIV_PAUSE)
        xml = arxiv_get(f"{ARXIV_API}?id_list={','.join(chunk)}&max_results={len(chunk)}")
        feed = feedparser.parse(xml)
        for e in feed.entries:
            pid = re.sub(r"v\d+$", "", e.id.split("/abs/")[-1])
            pdf = next((l.href for l in e.links if getattr(l, "type", "") == "application/pdf"), "")
            records.append({
                "id": pid,
                "title": e.title.replace("\n", " "),
                "authors": [a.name.replace(":", "").strip() for a in getattr(e, "authors", [])],
                "abstract": e.summary.replace("\n", " "),
                "published_at": datetime(*e.published_parsed[:6]).isoformat(),
                "updated_at": datetime(*e.updated_parsed[:6]).isoformat(),
                "category_primary": e.arxiv_primary_category["term"] if hasattr(e, "arxiv_primary_category") else "",
                "all_categories": [t["term"] for t in getattr(e, "tags", [])],
                "pdf_url": pdf,
            })
    return records


def nas_json(url: str, payload: dict | None = None, tries: int = 5, wait: int = 30):
    # The NAS can stall for a while (e.g. its own maintenance windows) — retry politely.
    for attempt in range(tries):
        try:
            if payload is None:
                req = urllib.request.Request(url)
            else:
                req = urllib.request.Request(
                    url, data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"}, method="POST",
                )
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:
            print(f"    NAS error (attempt {attempt + 1}/{tries}): {e}; retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"NAS unreachable: {url[:100]}")


def db_existing_ids(base_url: str, ids: list[str]) -> set[str]:
    # Existence check by id (immune to published_at landing on a different day, e.g. v2 dates)
    found: set[str] = set()
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        found |= {p["id"] for p in nas_json(f"{base_url}/api/papers?ids={','.join(chunk)}&compact=true")}
    return found


def bulk_insert(base_url: str, records: list[dict]) -> dict:
    return nas_json(f"{base_url}/api/papers/bulk-insert", payload={"papers": records})


def main() -> None:
    global ARXIV_PAUSE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", required=True)
    parser.add_argument("--to", dest="date_to", required=True)
    parser.add_argument("--base-url", default="http://nas:8000")
    parser.add_argument("--categories", default="cs.CV,cs.CL")
    parser.add_argument("--state", default=str(Path(__file__).with_name("backfill_state.json")))
    parser.add_argument("--dry-run", action="store_true", help="only report what would be added")
    parser.add_argument("--pause", type=float, default=ARXIV_PAUSE,
                        help="seconds between arXiv requests (raise for long sustained runs)")
    args = parser.parse_args()

    ARXIV_PAUSE = args.pause

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    day = datetime.strptime(args.date_from, "%Y-%m-%d").date()
    last = datetime.strptime(args.date_to, "%Y-%m-%d").date()

    state_path = Path(args.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done_days": [], "inserted": 0}

    grand_missing = grand_inserted = 0
    while day <= last:
        key = day.isoformat()
        if key in state["done_days"]:
            day += timedelta(days=1)
            continue

        listing = arxiv_ids_for_day(day, categories)
        in_db = db_existing_ids(args.base_url, listing) if listing else set()
        missing = [i for i in listing if i not in in_db]
        grand_missing += len(missing)
        print(f"{key}: arXiv={len(listing)} db={len(in_db)} missing={len(missing)}")

        if not args.dry_run:
            if missing:
                records = fetch_metadata(missing)
                result = bulk_insert(args.base_url, records)
                grand_inserted += result.get("inserted", 0)
                state["inserted"] += result.get("inserted", 0)
                print(f"    inserted={result.get('inserted')} skipped={result.get('skipped')}")
            state["done_days"].append(key)
            state_path.write_text(json.dumps(state, indent=1))

        day += timedelta(days=1)
        time.sleep(ARXIV_PAUSE)

    print(f"\nDone. missing={grand_missing} inserted={grand_inserted}")
    print("Reminder: POST /api/embeddings/backfill once so the new papers get vectors.")


if __name__ == "__main__":
    main()

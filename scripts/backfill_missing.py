"""Backfill papers the daily fetch window missed.

The daily worker only grabs the newest N announced papers sorted by
submittedDate, so papers announced late (or submitted while the instance was
down) never enter the DB. This script walks a submittedDate range day by day,
diffs the arXiv listing against the DB, and adds the missing papers through
POST /api/papers/add with push=false, so nothing is pushed individually —
qualifying papers go out with the next scheduled digest.

Usage:
    python scripts/backfill_missing.py --from 2026-02-05 --to 2026-08-23 \
        [--base-url http://nas:8000] [--categories cs.CV,cs.CL] \
        [--pace 4] [--dry-run]

Resumable: finished days are recorded in the state file (--state,
default backfill_state.json next to this script); rerunning skips them.
"""

import argparse
import json
import re
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ARXIV_API = "https://export.arxiv.org/api/query"
UA = {"User-Agent": "paper-agent-backfill/1.0"}
PAGE_SIZE = 200
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
            return ids
        time.sleep(ARXIV_PAUSE)


def db_existing_ids(base_url: str, ids: list[str]) -> set[str]:
    # Existence check by id (immune to published_at landing on a different day, e.g. v2 dates)
    found: set[str] = set()
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        url = f"{base_url}/api/papers?ids={','.join(chunk)}&compact=true"
        with urllib.request.urlopen(url, timeout=30) as r:
            found |= {p["id"] for p in json.load(r)}
    return found


def add_paper(base_url: str, arxiv_id: str) -> str:
    req = urllib.request.Request(
        f"{base_url}/api/papers/add",
        data=json.dumps({"input": arxiv_id, "push": False}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("message", "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", required=True)
    parser.add_argument("--to", dest="date_to", required=True)
    parser.add_argument("--base-url", default="http://nas:8000")
    parser.add_argument("--categories", default="cs.CV,cs.CL")
    parser.add_argument("--pace", type=float, default=4.0,
                        help="seconds between add calls (also paces the server's own arXiv fetches)")
    parser.add_argument("--state", default=str(Path(__file__).with_name("backfill_state.json")))
    parser.add_argument("--dry-run", action="store_true", help="only report what would be added")
    args = parser.parse_args()

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    day = datetime.strptime(args.date_from, "%Y-%m-%d").date()
    last = datetime.strptime(args.date_to, "%Y-%m-%d").date()

    state_path = Path(args.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done_days": [], "added": 0, "failed": []}

    grand_missing = grand_added = 0
    while day <= last:
        key = day.isoformat()
        if key in state["done_days"]:
            day += timedelta(days=1)
            continue

        listing = arxiv_ids_for_day(day, categories)
        seen: set[str] = set()
        listing = [i for i in listing if not (i in seen or seen.add(i))]
        in_db = db_existing_ids(args.base_url, listing)
        missing = [i for i in listing if i not in in_db]
        grand_missing += len(missing)
        print(f"{key}: arXiv={len(listing)} db={len(in_db)} missing={len(missing)}")

        if not args.dry_run:
            for i, mid in enumerate(missing, 1):
                try:
                    msg = add_paper(args.base_url, mid)
                    grand_added += 1
                    state["added"] += 1
                    if i % 20 == 0:
                        print(f"    {i}/{len(missing)} added")
                except Exception as e:
                    print(f"    ADD {mid} failed: {e}")
                    state["failed"].append(mid)
                time.sleep(args.pace)
            state["done_days"].append(key)
            state_path.write_text(json.dumps(state, indent=1))

        day += timedelta(days=1)
        time.sleep(ARXIV_PAUSE)

    print(f"\nDone. missing={grand_missing} added={grand_added} failed={len(state['failed'])}")
    if state["failed"]:
        print("Failed ids kept in state file; rerun to retry manually.")


if __name__ == "__main__":
    main()

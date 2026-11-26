<p align="center">
  <h1 align="center">📄 Paper Agent</h1>
  <p align="center">
    <em>Your personal AI-powered arXiv digest — fetch, score, summarize, and browse daily papers effortlessly.</em>
  </p>
  <p align="center">
    <a href="https://github.com/HarborYuan/paper_agent/actions/workflows/docker-publish.yml"><img src="https://github.com/HarborYuan/paper_agent/actions/workflows/docker-publish.yml/badge.svg" alt="Docker Build"></a>
    <img src="https://img.shields.io/badge/version-2.1.2-cyan" alt="Version">
    <img src="https://img.shields.io/badge/python-3.13+-blue?logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
    <img src="https://img.shields.io/badge/React-61DAFB?logo=react&logoColor=black" alt="React">
  </p>
</p>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔍 **Auto-Fetch** | Pulls new papers from arXiv daily (de-duplicated) |
| 🤖 **Verdict pipeline (Claude)** | ① Screen every new paper's title + abstract into a relevance tier (Haiku) → ② review the relevant ones on the first part of the paper: verdict *Must Read / Worth Reading / Skim / Skip* + relevance · novelty · evidence · reusability + affiliations (Sonnet) → ③ deep-read the Must Read / Worth Reading papers in full: final verdict, TL;DR, paragraph notes, flagged claims |
| 📖 **Bilingual reading page** | `/read/<id>`: the paper paragraph by paragraph — original English on the left, a Chinese gist and full translation on the right; questionable / big claims highlighted in the original with the reason; figures inline (broken TikZ figures and scaled tables cropped from the PDF) |
| ⭐ **Daily Picks** | `/picks`: Must Read / Worth Reading papers by day, with TL;DR, claim flags and project tags |
| 📁 **Projects** | Named collections of papers (web page + MCP). New papers are recalled for each project by embedding similarity to its seed papers and description and by the screen model; the reviewer confirms each match |
| 🔥 **Hot papers** | Popular papers from Hugging Face Daily Papers (upvotes / GitHub stars) get their own digest section, relevant or not, each pushed once |
| 💳 **Claude API or OpenRouter** | Chat models through the Claude API (Message Batches API at 50% off, prompt caching) or through OpenRouter (real time); a per-cycle budget cap trims or skips stages once it is used up |
| ⚙️ **Everything editable in the UI** | All `.env` keys (keys, models, budget, categories, schedule, profile, Lark webhook) edited from Settings, written back to the env file and hot-applied — secrets never leave the server |
| 🤝 **MCP server for agents** | `mcp_server/` exposes the instance to Claude Code & co.: semantic search, recent papers, people-of-interest lookup, paper details / full text, deep reads, projects, BibTeX, and write-back of scores and important people |
| 🔎 **Semantic search & related papers** | Title+abstract embeddings (voyage-4 via OpenRouter, 512-d), generated on ingestion and caught up every night: describe what you want instead of guessing title words; every paper page lists its nearest neighbours |
| 📚 **BibTeX library** | Citation entries for any arXiv paper (paper-page button / API / MCP): `@inproceedings{booktitle}` for conferences, `@article{journal}` for journals and preprints. Agent-driven — the server never guesses venues; the agent verifies unchecked entries (arXiv comment hints, DBLP, OpenReview, ...) and writes the verdict back once, so it is never looked up again. Can sync a whole pasted `.bib`. Cite keys never change |
| 📬 **Notifications** | Pushes daily digest to Lark (飞书) via webhook; an arXiv API outage (errors / empty feed after retries) is pushed as an alert instead of a misleading "no new papers" |
| 🌐 **Web UI** | Beautiful dark-theme interface with day-by-day infinite scroll |
| 🎚️ **Adjustable Threshold** | Filter papers by score with a live slider |
| 🔄 **On-demand deep read** | Deep-read any paper from its page or over MCP |
| 🏆 **Author Rankings** | Browse top authors ranked by paper count with time-range filtering |
| 👤 **Author Detail** | Edit author bio/website/affiliation and mark implementation authors for score boosting |
| 🐳 **Docker Ready** | Single-container deployment with LinuxServer.io-style config |

---


## 📋 Version History

Names are reserved for feature milestones; patch releases intentionally have no name.

| Version | Name | Highlights |
|---------|------|------------|
| **2.1.2** | *UI Update* | Author page rebuilt with the home-page cards and a shared top bar, loading light card records (`GET /api/authors/{name}/papers?view=card`); company logos back on the new cards (home, search, author page), readable in light and dark |
| **2.1.1** | *UI Update* | Reading page: papers whose arXiv HTML is broken (the reference list placed mid-section, later sections carrying their text in stray reference items) are read to the end instead of stopping at the misplaced reference list |
| **2.1.0** | *UI Update* | Home page rebuilt in the look of the reading and Picks pages (serif headings, paper cards with verdict pills, light / dark), and made fast: one call per publication day (`GET /api/papers/feed`) with light card records — no full text, only the papers above the score filter, days without any skipped on the server — instead of every paper of the day with its full text (a busy day was ~12 MB); index on `paper.published_at` (migration 006). Every author on the reading page; wherever a list is still shortened (home cards, Picks, the Lark digest) the last author stays visible (`A, B, C, D, … +N, Z`). Author names link to the author page on the home cards, the paper page, the reading page and Picks (Picks cards restructured so links never nest). Fixed: names with an apostrophe broke the author list on the paper page |
| **2.0.0** | *Pipeline Update* | **Breaking.** Scoring rebuilt on Claude: screen (relevance tier) → review (verdict Must Read / Worth Reading / Skim / Skip, relevance · novelty · evidence · reusability, affiliations) → deep read (final verdict, TL;DR, paragraph gists, claim flags) + Chinese translation; verdicts map onto the 0-100 score (Worth Reading 85-91, Must Read 92-99) so filters and the push threshold keep working. Claude API with the Message Batches API and prompt caching, or OpenRouter's Anthropic-compatible endpoint (`CHAT_PROVIDER`); per-cycle spend cap (`CLAUDE_MONTHLY_BUDGET`) and a nightly deep-read cap. Bilingual reading page `/read/<id>` (arXiv HTML split into paragraphs, broken TikZ figures / scaled tables cropped from the PDF), Daily Picks `/picks`, Projects (embedding + screen recall, reviewer confirmation; web page + 7 MCP tools), hot papers from Hugging Face Daily Papers, deep-read API + MCP tools. Embeddings generated on ingestion and caught up nightly. **Removed:** the two-stage pipeline and its settings, long structured summaries (TL;DR only), daily / weekly / monthly reports, cost estimates, the legacy `OPENAI_API_KEY` / `OPENAI_BASE_URL`. Old scores, summaries and reviews are kept and reused |
| **1.3.0** | *Bib2 Update* | `fix_bibtex` now cuts every paper entry of a pasted `.bib` down to four fields (title / author / booktitle or journal / year): published `@inproceedings` / `@article` entries lose pages, volume, publisher, doi, url, …, unpublished arXiv entries become `journal = {arXiv preprint arXiv:<id>}`, values are copied as written (`@string` macros kept), other entry kinds stay untouched; official author lists — `set_bibtex_status` takes `authors` for a published paper and from then on they replace the arXiv list in library entries and `fix_bibtex` rewrites (new `bibentry.published_authors`, migration 005); stricter venue naming in the MCP tool descriptions (bare conference abbreviations, `NIPS` up to 2017 / `NeurIPS` from 2018, no extra fields); `skills/fix-bib` — a stateless Claude Code skill that does the same one-shot fix without a server, for collaborators |
| **1.2.1** | — | BibTeX titles wrapped in double braces (`title = {{...}}`) so styles that lowercase titles keep acronyms like SAM / OMG-Seg / 3D; MCP install docs now recommend pinning to a release tag via `uvx --from git+...@vX.Y.Z` |
| **1.2.0** | *Bib Update* | BibTeX library driven by the agent over MCP (`get_bibtex`, `bibtex_venue_hints`, `set_bibtex_status`, `fix_bibtex`): any arXiv paper becomes `@inproceedings{booktitle}` (conference) / `@article{journal}` (journal or arXiv preprint); the server never guesses venues — the agent verifies `needs_check` entries and writes the verdict back once (`published` is final, "still a preprint" re-flagged after 30 days); pasted `.bib` files synced with stable cite keys; BibTeX copy button on the paper page. arXiv API hardening: retries with back-off, error / empty feeds detected, and an outage now pushes a Lark alert instead of the misleading "no new papers" message |
| **1.1.0** | *Deep Read Update* | Stage-2 reviewer reads agentically: 20k-char triage pass, then ONE optional extended read (120k chars, new `STAGE2_DEEP_TEXT_CHAR_LIMIT`) when the verdict hinges on unseen experiments — `deep_read` + its reason stored and shown in the UI; prompt overhaul: summaries gain `## TL;DR` (single shared extractor now feeds digest / reports / API teasers), writing-craft sections (Teaser Figure, Intro Narrative, Method Writing), an explicit Reading Recommendation verdict, grounding rules ("Not mentioned." instead of guessing), CN 说人话 style with technical terms kept in English; stage-1/stage-2 relevance tiers unified; affiliation prompt gets a canonical list of university short forms |
| **1.0.4** | — | Follow-up to 1.0.3 after robustness testing on real arXiv data: short papers keep their HTML (structural `<article>` check replaces a length heuristic), legacy ids (`cs/0112017`) try HTML too, unexpanded LaTeXML macros no longer pollute the head of the text, nested `<math>` stops double-emitting |
| **1.0.3** | — | arXiv HTML (`arxiv.org/html/{id}`) preferred over PDF for full text — reading-order text, LaTeX kept from MathML `alttext`, arXiv page chrome stripped; PDF fallback now streams with a 30 MB cap and parses off the event loop; scheduled run no longer skips papers already sitting as `NEW` (backfills were being stranded) |
| **1.0.2** | — | `POST /api/papers/bulk-insert` (up to 1000 papers, version-suffix stripping + dedupe), backfill script fetches metadata locally via `id_list` so the server never calls arXiv |
| **1.0.1** | — | `push` flag on `POST /api/papers/add` and `/api/papers/re-score-date` — papers stay `SUMMARIZED` for the next scheduled digest instead of firing individual notifications; existing summaries reused; `scripts/backfill_missing.py` |
| **1.0.0** | *Agent Update* | MCP server (`paper-agent-mcp`, 13 tools), agent endpoints: `GET /api/papers/recent`, fuzzy batch `POST /api/authors/lookup` (people of interest), `POST /api/authors/bulk`, `POST /api/authors/reindex` |
| **0.6.0** | *Semantic Update* | Paper embeddings (OpenRouter `/embeddings`, default `voyageai/voyage-4` @512), semantic search toggle on the main page, Related papers on paper pages, embedding-based topic clusters fed into reports, Embeddings card in Settings (coverage + backfill), embedding cost in usage/estimates |
| **0.5.0** | *Radar Update* | Daily / weekly / monthly trend reports (Python-computed stats + LLM narrative), Reports page with on-demand generate / push / delete, report model slot + cost estimate, `Cache-Control` on the app shell so upgrades never serve a stale frontend |
| **0.4.0** | *Scoring Update* | Two-stage scoring (cheap screen → strong review w/ paper text + quality rubric), OpenRouter provider, per-stage model picker in Settings, real cost accounting + cost estimates, profile-aware "Relevance to Me" summary section, full `.env` editing from the UI (write-back + hot reload, secrets masked). **Breaking:** all API routes moved under `/api/` |
| **0.3.1** | — | Authors in digest, rest-day notification, daily scoring stats |
| **0.3.0** | *Search Update* | Global search by title frontend/backend |
| **0.2.1** | — | Edit author details, claim important authors for score boost |
| **0.2.0** | *Authors Update* | Author ranking pages with time-range filter (7d/30d/90d/180d/360d/All) |
| **0.1.0** | *Lark Update* | Replaced Telegram/Pushover with Lark (飞书) webhook, date-grouped digests |
| **0.0.3** | — | Markdown-rendered AI summaries, score threshold slider, per-paper refresh, README rewrite |
| **0.0.2** | — | Docker deployment, auto-update scheduler, WebSocket log viewer |
| **0.0.1** | — | Initial release: fetch, score, summarize, notify |

---

## 🧠 How scoring works (v2)

```
arXiv fetch ─► ① screen (Haiku, title + abstract) ─► relevance ≥ SCREEN_MIN_RELEVANCE or a project candidate? ──no──► FILTERED
                                                         │ yes
                                                         ▼
               ② review (Sonnet, abstract + first STAGE2_TEXT_CHAR_LIMIT chars)
               verdict + relevance · novelty · evidence · reusability + affiliations + project matches
                                                         │ Must Read / Worth Reading
                                                         ▼
               ③ deep read (Sonnet, whole paper as paragraphs) ─► final verdict, TL;DR, gists, claim flags
               + translation (Haiku)                         ─► reading page, Lark digest
```

- Score: screen = 20 × relevance; review / deep read map the verdict onto a band — Must Read 92-99, Worth Reading 85-91, Skim 60-84, Skip 20-59 (position from novelty + evidence + reusability). The digest pushes papers ≥ 85. Important authors are lifted to ≥ 90; a manual score overrides everything.
- Every relevance judgement follows the profile's tiers (all core items equal; analyses, benchmarks and data count like methods; agents on any platform are agents).
- Nightly stages go through the Message Batches API (one batch per stage, 50% off; anything unfinished after `BATCH_MAX_WAIT_MINUTES` is retried in real time). On-demand deep reads run in real time.
- `CLAUDE_MONTHLY_BUDGET` caps the estimated spend per billing cycle (`CLAUDE_BUDGET_RESET_DAY`); stages are trimmed or skipped once it is used up and the papers wait. `DEEP_READ_MAX_PER_RUN` caps deep reads per night (Must Read first).
- Papers scored by the old two-stage pipeline keep their scores; a deep read of such a paper reuses its old review.

### Embeddings & retrieval

Every paper is embedded (title + abstract) when it enters the library, and each nightly run embeds whatever is still missing (up to `EMBED_CATCHUP_PER_RUN`), through OpenRouter's `/embeddings` endpoint — default `voyageai/voyage-4` truncated to 512 dimensions (≈ $0.001/day). Vectors are stored in the `paperembedding` table (model + dim recorded, so a model switch is detected) and served from an in-memory, L2-normalised matrix: brute-force cosine, no vector database. They power the **Semantic** toggle of the search box, **Related papers** on every paper page, and project recall.

`compact=true` (and the POST search by default) returns small agent-friendly records — `id, title, authors, published_at, category, score, user_score, status, main_affiliation, main_company, reason, tldr, has_summary, pdf_url, abs_url` (+ `similarity`) — no full text or raw JSON.

### BibTeX library

Four fields per entry, typed by where the paper appeared:

```bibtex
@article{yuan2026great,  journal   = {arXiv preprint arXiv:2602.00001}, ...}   % preprint
@inproceedings{...,      booktitle = {CVPR}, year = {2026}}                     % conference: short name
@article{...,            journal   = {IEEE TPAMI}, year = {2026}}               % journal: short name if well known, else full name
```

Freshly fetched arXiv papers are normally not accepted anywhere, so the server never looks venues up. Entries start as `unchecked`; when citing, the agent (MCP) checks every entry in `needs_check` — `bibtex_venue_hints` gives the current arXiv comment / journal_ref ("Accepted to CVPR 2026"), the agent confirms elsewhere if needed — and writes the verdict back with `set_bibtex_status`. `published` is final (never checked again); `preprint` ("checked, not yet") is trusted for 30 days, then flagged again. The venue is stored exactly as the agent writes it; the naming convention (conference short names, short names for well-known journals such as IEEE TPAMI / IJCV, otherwise the full name) is part of the MCP tool descriptions. Titles are wrapped in double braces (`title = {{...}}`) so styles that lowercase titles keep SAM / OMG-Seg / 3D intact; `fix_bibtex` keeps the title text of a pasted entry as written. Cite keys (`lastname` + arXiv year + first title word) are fixed at creation so LaTeX sources keep compiling.

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
uv sync
```

### 2. Configure

Copy `.env.example` → `.env` and fill in your API key — everything else can be changed later from the **Settings** page (it writes back to this file):

```env
DATABASE_URL="sqlite:///./paper_agent.db"
ANTHROPIC_API_KEY="sk-ant-..."          # chat models (or CHAT_PROVIDER="openrouter" to use the OpenRouter key)
OPENROUTER_API_KEY="sk-or-..."          # embeddings

# Defaults (override anytime from the Settings page)
LLM_MODEL_STAGE1="claude-haiku-5-5"     # screen
LLM_MODEL_STAGE2="claude-sonnet-5-5"    # review
LLM_MODEL_SUMMARY="claude-sonnet-5-5"   # deep read
CLAUDE_MONTHLY_BUDGET=80

# Optional: Lark Notification
LARK_WEBHOOK_URL="https://open.larksuite.com/open-apis/bot/v2/hook/..."
```

### 3. Run

```bash
# Backend
uv run uvicorn src.main:app --reload

# Frontend (in another terminal)
cd frontend && npm install && npm run dev
```

Open **[http://localhost:5173](http://localhost:5173)** to browse papers.

### 4. Trigger a Fetch

```bash
curl -X POST http://localhost:8000/api/run
```

---

## 🐳 Docker Deployment

This project supports a **LinuxServer.io-style** single-container deployment.

```bash
# Build
docker build -t paper-agent .

# Run
docker-compose up -d
```

| Variable | Description | Default |
|----------|-------------|---------|
| `PUID` / `PGID` | User/Group ID | `1000` |
| `DATABASE_URL` | SQLite path | `sqlite:////config/paper_agent.db` |
| `ANTHROPIC_API_KEY` | Claude Console key (chat models when `CHAT_PROVIDER=anthropic`) | — |
| `OPENROUTER_API_KEY` | OpenRouter key: embeddings, and chat models when `CHAT_PROVIDER=openrouter` | — |
| `CHAT_PROVIDER` | `anthropic` (Batch API available) or `openrouter` (real time only) | `anthropic` |
| `LLM_MODEL_STAGE1` / `LLM_MODEL_STAGE2` / `LLM_MODEL_SUMMARY` / `LLM_MODEL_TRANSLATE` | Screen / review / deep read / translation models (non-Claude ids fall back to the defaults) | `claude-haiku-5-5` / `claude-sonnet-5-5` / `claude-sonnet-5-5` / `claude-haiku-5-5` |
| `SCREEN_MIN_RELEVANCE` / `DEEP_READ_MAX_PER_RUN` | Screen tier needed for review / deep reads per night | `4` / `12` |
| `LLM_USE_BATCH` / `BATCH_MAX_WAIT_MINUTES` | Message Batches API for nightly stages / wait before real-time retry | `true` / `240` |
| `CLAUDE_MONTHLY_BUDGET` / `CLAUDE_BUDGET_RESET_DAY` | Spend cap per billing cycle (USD) / day the cycle resets | `80` / `1` |
| `PROJECT_SIM_THRESHOLD` | Embedding cosine for project recall | `0.74` |
| `HOT_ENABLED` / `HOT_MIN_UPVOTES` / `HOT_MIN_STARS` / `HOT_MAX_PER_RUN` | Hot-paper section | `true` / `50` / `500` / `5` |
| `PUBLIC_BASE_URL` | Base URL for reading-page links in Lark, e.g. `http://nas:8000` | — |
| `SUMMARY_LANGUAGE` | `EN` or `CN` | `EN` |
| `ENABLE_AUTO_UPDATE` | Daily auto-fetch | `false` |
| `AUTO_UPDATE_TIME` | Fetch time (UTC) | `04:00` |
| `ARXIV_CATEGORIES` | JSON list of arXiv categories to fetch | `["cs.CV","cs.CL","cs.AI"]` |
| `USER_PROFILE` | Your research-interest prompt (drives scoring + summaries) | generic CV/MM profile |
| `LARK_WEBHOOK_URL` | Lark (飞书) bot webhook; empty = no notifications | — |
| `STAGE2_TEXT_CHAR_LIMIT` | Chars of paper text shown to the reviewer | `20000` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | Embedding model (OpenRouter `/embeddings/models`) and dimensions (0 = native) | `voyageai/voyage-4` / `512` |

Everything except `PUID`/`PGID`/`DATABASE_URL` can also be edited at runtime from the Settings page (see below). The image exposes port `8000` and persists DB + `.env` in the `/config` volume.

**Access:** Web UI at `http://localhost:8000` · API under `http://localhost:8000/api/...` · API docs at `http://localhost:8000/docs`

### Upgrading from 1.x to 2.0

1. `docker compose pull && docker compose up -d`. New tables are created on first start; existing tables are unchanged.
2. In Settings, set `ANTHROPIC_API_KEY` (or switch "Chat models via" to OpenRouter), set `PUBLIC_BASE_URL`, and `CLAUDE_BUDGET_RESET_DAY` to your billing day. Old non-Claude model ids are ignored (a warning on the Settings page says which).
3. Existing papers keep their scores, summaries (the paper page shows only the TL;DR) and reviews; the reports table is no longer used. Obsolete keys left in `/config/.env` (`STAGE2_THRESHOLD`, `REPORT_*`, `OPENAI_*`, …) are ignored.

### Upgrading from 0.3.x to 0.4

1. Back up `./data/paper_agent.db` (optional — the schema migration only adds columns and is automatic on first start).
2. Add `OPENROUTER_API_KEY=sk-or-...` to `./data/.env` (or set it in the Settings page after starting). Without it the legacy `OPENAI_API_KEY` path is used and non-OpenAI stage-2 models fall back to the stage-1 model.
3. `docker compose pull && docker compose up -d`. Existing papers keep their old single-stage scores; new papers get two-stage scores.
4. **Breaking:** every API path now starts with `/api/` (e.g. `POST /api/run`). Update any external scripts.

---

## ⚙️ Configuration & precedence

All configuration lives in one dotenv file — `/config/.env` in Docker (the volume), `./.env` in local dev — and **every key can be edited from the Settings page**. Saving rewrites only the changed keys in that file (comments, order and other keys are preserved byte-for-byte, written atomically) and hot-applies the new values, so no restart is needed — including the daily schedule, which is re-armed live. Secrets (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `LARK_WEBHOOK_URL`) are never sent to the browser: the UI only sees *configured + last 4 chars*; leave a secret field blank to keep it, type a new value to replace it.

Resolution order, highest first:

| # | Source | Notes |
|---|--------|-------|
| 1 | **Process environment variables** (`environment:` in `docker-compose.yml`, shell vars) | Outrank the file. The Settings page flags such keys with an **env var** badge and warns that saving will not take effect until the variable is removed from the container environment. |
| 2 | **The env file** — `/config/.env` (Docker) or `./.env` (local) | What the Settings page reads and writes. If both exist, `./.env` wins (pydantic-settings loads `/config/.env` then `.env`). |
| 3 | Code defaults in `src/config.py` | Used until you save a value. |

Read-only in the UI: `DATABASE_URL` (set by the container) and `DEV_COMMIT` (developer flag). The `USER_PROFILE` prompt is edited in its own card and stored in the same file (multi-line values are dotenv-escaped and round-trip exactly).

---

## 📖 API Reference

All endpoints are served under the **`/api`** prefix (e.g. `GET /api/papers`) so they never collide with frontend routes. `/docs`, `/openapi.json` and a root `/health` liveness probe stay at the root.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/run` | Trigger fetch + score + summarize cycle |
| `GET` | `/api/papers` | List papers (`?date=YYYY-MM-DD`, `?status=`, `?ids=a,b,c`, `?compact=true`) |
| `GET` | `/api/papers/search` | Search papers by title (`?q=query`, `?compact=true`, `?view=card` for the home-page card records) |
| `GET` | `/api/papers/{id}` | Get single paper details |
| `POST` | `/api/papers/add` | Add paper by arXiv ID or URL |
| `POST` | `/api/papers/{id}/deep-read?force=` | Deep read now (real time): review if needed, final verdict, TL;DR, paragraph notes, claim flags, translation |
| `GET` | `/api/papers/{id}/reading?full=` | Deep-read status, verdict and verified claim flags (`full=true`: units, notes, translations) |
| `POST` | `/api/papers/{id}/resummarize` | Redo the deep read |
| `PATCH` | `/api/papers/{id}/score?score=N` | Set a manual score (overrides AI, disables re-scoring) |
| `POST` | `/api/papers/re-score-date?date=YYYY-MM-DD` | Re-run the pipeline on all papers of a date (Batch API) |
| `GET` / `POST` / `PATCH` / `DELETE` | `/api/projects` · `/api/projects/{id or name}` | List / create (`name`, `description`, `keywords`, `seed_paper_ids`) / edit / delete projects |
| `POST` / `DELETE` | `/api/projects/{key}/papers` · `/api/projects/{key}/papers/{id}` | Add papers (`manual` or `seed`) / remove one |
| `GET` | `/api/projects/{key}/suggestions?k=` | Library papers closest to the project that are not in it yet |
| `GET` | `/api/claude/budget` · `/api/claude/models` | Spend this billing cycle vs the cap · Claude models with list prices |
| `GET` | `/api/papers/feed?before=YYYY-MM-DD&min_score=N` | Home-page feed: the newest day on or before `before` with a paper scoring ≥ `min_score`, all such papers as light card records, the day's total and `next` (the next earlier such day, `null` at the end) |
| `GET` | `/api/papers/start-date` · `/api/papers/next-date?date=` | Pagination helpers for the day-by-day feed |
| `GET` | `/api/papers/recent?days=&min_score=&status=&category=&limit=&compact=` | Recent papers, newest first (compact by default) |
| `GET` | `/api/authors` | Ranked author list (optional `?days=N`) |
| `POST` | `/api/authors/lookup` | `{"names": [...], "days"?, "min_score"?, "limit_per_author", "mark_important"?}` — fuzzy people-of-interest lookup: matched name variants + their papers |
| `POST` | `/api/authors/bulk` · `/api/authors/reindex` | Upsert many authors (is_important, bio, website, affiliation) · rebuild the fuzzy name index |
| `GET` | `/api/authors/{name}/papers` | Papers by author (optional `?days=N`) |
| `GET` / `PATCH` | `/api/authors/{name}/details` · `/api/authors/{name}` | Read / edit author bio, website, affiliation, `is_important` (score boost) |
| `GET` | `/api/profile` | Current `USER_PROFILE` text |
| `GET` | `/api/settings` | Every editable setting with effective value, source (env var / file / default) and schema; secrets masked |
| `PUT` | `/api/settings` | `{"values": {KEY: value, ...}}` — validates, rewrites the env file, hot-applies (schedule changes re-arm the scheduler) |
| `PUT` | `/api/settings/profile` | `{"profile": "..."}` — update `USER_PROFILE` |
| `GET` | `/api/settings/llm` | Current models, gates, provider status, warnings |
| `PUT` | `/api/settings/llm` | Update `stage1_model` / `stage2_model` / `summary_model` / `translate_model` (Claude ids) |
| `GET` | `/api/llm/usage` | Spend: today / 7d / 30d / all-time + per task/model breakdown |
| `GET` | `/api/papers/semantic-search?q=&limit=&days=&min_score=&category=&compact=&view=` | Embedding search; returns papers with cosine `similarity` |
| `POST` | `/api/papers/semantic-search` | Agent-friendly search: `{"query"?, "paper_ids"? (seeds), "days"/"since"/"until", "min_score", "status", "category", "exclude_ids", "limit", "compact"}` |
| `GET` | `/api/papers/{id}/related?k=` | Nearest neighbours of a paper (`available=false` until it has a vector) |
| `GET` / `POST` | `/api/embeddings/status` · `/api/embeddings/backfill` · `/api/embeddings/reload` · `/api/embeddings/models` | Coverage, background backfill, index reload, embedding model list |
| `GET` | `/api/bibtex?ids=` | BibTeX for arXiv ids (new ones added as unchecked); no `ids` = whole library. Returns `bibtex`, per-entry status and `needs_check` |
| `GET` | `/api/bibtex/hints?ids=` | Read-only venue evidence from the current arXiv record (raw comment / journal_ref / DOI) |
| `PUT` | `/api/bibtex/{id}/status` | `{"status": "published", "venue": "CVPR", "venue_type": "conference", "year": 2026, "evidence"?}` — or `"preprint"` (checked, not yet) / `"unchecked"` (reset) |
| `GET` / `DELETE` | `/api/bibtex/{id}/entry` | One entry (created on demand) / remove it from the library |
| `POST` | `/api/bibtex/fix` | `{"bibtex": "..."}` — sync a pasted .bib with the library (no lookups); returns what still `needs_check` |
| `WS` | `/api/ws/logs` | Live log stream (used by the in-app log viewer) |
| `GET` | `/health` · `/api/health` | Liveness probe |
| `GET` | `/read/{id}` · `/picks?date=&days=` | Bilingual reading page · Daily Picks (server-rendered HTML) |

---

## 🤝 MCP server (agents / Claude Code)

`mcp_server/` is a small separate package (`paper-agent-mcp`, stdio) with explicit tools over the API — see [`mcp_server/README.md`](mcp_server/README.md) for the tool list. Register it in Claude Code, pinned to the release that matches your server:

```bash
claude mcp add --scope user paper-agent -- uvx --from "git+https://github.com/HarborYuan/paper_agent@v2.0.0#subdirectory=mcp_server" paper-agent-mcp --base-url http://nas:8000
```

(To hack on the MCP server itself, register `uv run --directory /path/to/paper_agent/mcp_server paper-agent-mcp ...` instead — see its README.)

Typical asks: *"what did the people in my POI list publish this month"* (`papers_by_people`), *"papers from the last two weeks related to 2608.19556"* (`search_papers` with seeds), *"read 2608.18607 for me"* (`get_paper` with text), *"deep-read 2611.23034"* (`deep_read_paper` / `get_deep_read`), *"add these three papers to my-tokenizer-project"* (`add_papers_to_project`), *"mark 2608.18607 as 95, I read it"* (`set_user_score`).

---

## 🧪 Development

```bash
uv sync                                  # backend deps (Python 3.13)
uv run pytest -q                         # unit tests (in-memory SQLite, LLM calls mocked)
uv run uvicorn src.main:app --reload     # API on :8000 (serves frontend/dist if it exists)
cd frontend && npm install && npm run dev   # Vite dev server on :5173, proxies /api to :8000
cd frontend && npm run build             # production bundle -> frontend/dist
```

Layout: `src/main.py` (FastAPI routes), `src/worker.py` (fetch → embed → hot refresh → verdict pipeline → notify), `src/services/` (verdict_pipeline, claude_runner, claude_budget, reading_service, reading_page, project_service, hot_service, arxiv, pdf, embedding_service, notifier, settings_service, env_file, usage_service), `src/prompts/*.jinja2`, `src/migrations.py` (numbered, run automatically at startup), `frontend/src/` (React 19 + Vite + Tailwind). Docker image = `node` build stage for the frontend + `linuxserver/baseimage-alpine` + `uv`; pushing a `v*.*.*` tag publishes `harbory/paper-agent:<version>` and `:latest`, pushing `main` publishes `:dev`.

<p align="center">
  <h1 align="center">📄 Paper Agent</h1>
  <p align="center">
    <em>Your personal AI-powered arXiv digest — fetch, score, summarize, and browse daily papers effortlessly.</em>
  </p>
  <p align="center">
    <a href="https://github.com/HarborYuan/paper_agent/actions/workflows/docker-publish.yml"><img src="https://github.com/HarborYuan/paper_agent/actions/workflows/docker-publish.yml/badge.svg" alt="Docker Build"></a>
    <img src="https://img.shields.io/badge/version-1.0.4-cyan" alt="Version">
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
| 🤖 **Two-Stage LLM Scoring** | Stage 1: cheap screen on title+abstract (recall). Stage 2: stronger model reads the start of the PDF and judges relevance **and quality** (precision). Final score = stage 2 |
| 🔌 **OpenRouter / any OpenAI-compatible API** | One key, hundreds of models; pick the model per stage from the Settings page |
| ⚙️ **Everything editable in the UI** | All `.env` keys (provider keys, models, thresholds, categories, schedule, profile, Lark webhook) edited from Settings, written back to the env file and hot-applied — secrets never leave the server |
| 💸 **Cost tracking & estimates** | Real spend per call (from provider usage), today / 7d / 30d totals, and a live per-day / per-month estimate for any model selection |
| 📝 **Smart Summaries** | Generates personalized markdown summaries with TL;DR, contributions, methodology |
| 🤝 **MCP server for agents** | `mcp_server/` exposes the instance to Claude Code & co.: semantic search, recent papers, people-of-interest lookup (fuzzy names), paper details / full text, reports, and write-back of scores and important people |
| 🔎 **Semantic search & related papers** | Title+abstract embeddings (voyage-4 via OpenRouter, 512-d): describe what you want instead of guessing title words; every paper page lists its nearest neighbours; reports cluster papers by embedding before the LLM writes the topic section |
| 📰 **Daily / Weekly / Monthly Reports** | LLM-written trend reports over the selected papers — topic clusters, institution counts vs. previous period, must-read top 5, signals — stored in the app and pushed to Lark right after the digest |
| 📬 **Notifications** | Pushes daily digest to Lark (飞书) via webhook |
| 🌐 **Web UI** | Beautiful dark-theme interface with day-by-day infinite scroll |
| 🎚️ **Adjustable Threshold** | Filter papers by score with a live slider |
| 🔄 **Per-Paper Refresh** | Re-summarize any paper on demand |
| 🏆 **Author Rankings** | Browse top authors ranked by paper count with time-range filtering |
| 👤 **Author Detail** | Edit author bio/website/affiliation and mark implementation authors for score boosting |
| 🐳 **Docker Ready** | Single-container deployment with LinuxServer.io-style config |

---


## 📋 Version History

Names are reserved for feature milestones; patch releases intentionally have no name.

| Version | Name | Highlights |
|---------|------|------------|
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

## 🧠 How scoring works (v0.4)

```
arXiv fetch ─► Stage 1 (cheap model, title+abstract) ─► score ≥ STAGE2_THRESHOLD? ──no──► FILTERED
                                                            │ yes
                                                            ▼
                              Stage 2 (strong model, abstract + first ~8k chars of the PDF,
                              rubric = relevance · novelty · quality · clarity) ─► final score
                                                            │
                                   final ≥ SCORE_THRESHOLD ─┴─► full-text summary ─► Lark digest
```

- Stage 1 is tuned for **recall** (when torn between two relevance levels, pick the higher); stage 2 for **precision** and is the only stage that judges *quality of evidence* (baselines, ablations, scale, code).
- The PDF text fetched for stage 2 is cached on the paper and reused by summarization.
- Every LLM call is logged with tokens + cost (`GET /api/llm/usage`); the Settings page shows real spend and a live estimate for any model selection.
- A manual score (`PATCH /api/papers/{id}/score`, or click the score badge in the UI) still overrides everything and disables re-scoring.

### Embeddings & retrieval

Every new paper is embedded (title + abstract) during the run through the provider's OpenAI-compatible `/embeddings` endpoint — default `voyageai/voyage-4` truncated to 512 dimensions (≈ $0.001/day; backfilling history ≈ $0.02 per 1k papers). Vectors are stored in the `paperembedding` table (model + dim recorded, so a model switch is detected and shown as "missing" until you Backfill) and served from an in-memory, L2-normalised matrix: brute-force cosine, no vector database. Three things use it: the **Semantic** toggle of the search box, **Related papers** at the bottom of every paper page, and the topic clusters that are pre-computed for reports (k-means, cosine) so the LLM's "Topic Trends" starts from real structure.

`compact=true` (and the POST search by default) returns small agent-friendly records — `id, title, authors, published_at, category, score, user_score, status, main_affiliation, main_company, reason, tldr, has_summary, pdf_url, abs_url` (+ `similarity`) — no full text or raw JSON.

### Reports

After the digest, the run generates whichever reports are due and sends them as extra Lark cards right behind it:

| Report | When | Covers |
|---|---|---|
| 📰 Daily | after every run that pushed papers | the papers pushed in that run |
| 📊 Weekly | on `REPORT_WEEKLY_DAY` (default Monday, UTC) | the previous 7 days (papers ≥ `SCORE_THRESHOLD`) |
| 📈 Monthly | on the 1st | the previous calendar month |

Python computes the statistics first (selected / fetched / stage-2 counts, company & university counts **with deltas vs. the previous period**, categories, top and important authors, score distribution, LLM cost); the report model then writes the narrative from those numbers plus the paper list — topic clusters with cited arXiv ids, institution moves, must-read top 5, emerging signals. Reports live in the **Reports** page (generate any period on demand, push to Lark, delete) and are written in `SUMMARY_LANGUAGE`.

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
OPENROUTER_API_KEY="sk-or-..."          # or legacy OPENAI_API_KEY / OPENAI_BASE_URL

# Default models (override anytime from the Settings page)
LLM_MODEL_STAGE1="openai/gpt-4o-mini"
LLM_MODEL_STAGE2="anthropic/claude-sonnet-5"
LLM_MODEL_SUMMARY="openai/gpt-4o-mini"
STAGE2_THRESHOLD=60    # stage-1 score that triggers the stage-2 review
SCORE_THRESHOLD=85     # final score that triggers summary + notification

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
| `OPENROUTER_API_KEY` | OpenRouter API key (preferred; `OPENAI_API_KEY`+`OPENAI_BASE_URL` still work as fallback) | — |
| `LLM_MODEL_STAGE1` / `LLM_MODEL_STAGE2` / `LLM_MODEL_SUMMARY` | Model ids per task (editable in the UI, written back to `/config/.env`) | `openai/gpt-4o-mini` / `anthropic/claude-sonnet-5` / `openai/gpt-4o-mini` |
| `STAGE2_THRESHOLD` / `SCORE_THRESHOLD` | Stage-2 trigger / summarize+notify thresholds | `60` / `85` |
| `SUMMARY_LANGUAGE` | `EN` or `CN` | `EN` |
| `ENABLE_AUTO_UPDATE` | Daily auto-fetch | `false` |
| `AUTO_UPDATE_TIME` | Fetch time (UTC) | `04:00` |
| `ARXIV_CATEGORIES` | JSON list of arXiv categories to fetch | `["cs.CV","cs.CL","cs.AI"]` |
| `USER_PROFILE` | Your research-interest prompt (drives scoring + summaries) | generic CV/MM profile |
| `LARK_WEBHOOK_URL` | Lark (飞书) bot webhook; empty = no notifications | — |
| `STAGE2_TEXT_CHAR_LIMIT` | Chars of PDF text shown to the stage-2 reviewer | `8000` |
| `LLM_MODEL_REPORT` | Model for the trend reports | `anthropic/claude-sonnet-5` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | Embedding model (OpenRouter `/embeddings/models`) and dimensions (0 = native) | `voyageai/voyage-4` / `512` |
| `REPORT_DAILY_ENABLED` / `REPORT_WEEKLY_ENABLED` / `REPORT_MONTHLY_ENABLED` | Which reports to generate and push | `true` |
| `REPORT_WEEKLY_DAY` | Weekday for the weekly report (0 = Monday … 6 = Sunday, UTC) | `0` |

Everything except `PUID`/`PGID`/`DATABASE_URL` can also be edited at runtime from the Settings page (see below). The image exposes port `8000` and persists DB + `.env` in the `/config` volume.

**Access:** Web UI at `http://localhost:8000` · API under `http://localhost:8000/api/...` · API docs at `http://localhost:8000/docs`

### Upgrading from 0.3.x to 0.4

1. Back up `./data/paper_agent.db` (optional — the schema migration only adds columns and is automatic on first start).
2. Add `OPENROUTER_API_KEY=sk-or-...` to `./data/.env` (or set it in the Settings page after starting). Without it the legacy `OPENAI_API_KEY` path is used and non-OpenAI stage-2 models fall back to the stage-1 model.
3. `docker compose pull && docker compose up -d`. Existing papers keep their old single-stage scores; new papers get two-stage scores.
4. **Breaking:** every API path now starts with `/api/` (e.g. `POST /api/run`). Update any external scripts.

---

## ⚙️ Configuration & precedence

All configuration lives in one dotenv file — `/config/.env` in Docker (the volume), `./.env` in local dev — and **every key can be edited from the Settings page**. Saving rewrites only the changed keys in that file (comments, order and other keys are preserved byte-for-byte, written atomically) and hot-applies the new values, so no restart is needed — including the daily schedule, which is re-armed live. Secrets (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `LARK_WEBHOOK_URL`) are never sent to the browser: the UI only sees *configured + last 4 chars*; leave a secret field blank to keep it, type a new value to replace it.

Resolution order, highest first:

| # | Source | Notes |
|---|--------|-------|
| 1 | **Process environment variables** (`environment:` in `docker-compose.yml`, shell vars) | Outrank the file. The Settings page flags such keys with an **env var** badge and warns that saving will not take effect until the variable is removed from the container environment. |
| 2 | **The env file** — `/config/.env` (Docker) or `./.env` (local) | What the Settings page reads and writes. If both exist, `./.env` wins (pydantic-settings loads `/config/.env` then `.env`). |
| 3 | Code defaults in `src/config.py` | Shown with a **default** badge until you save a value. |

Read-only in the UI: `DATABASE_URL` (set by the container) and `DEV_COMMIT` (developer flag). The `USER_PROFILE` prompt is edited in its own card and stored in the same file (multi-line values are dotenv-escaped and round-trip exactly).

---

## 📖 API Reference

All endpoints are served under the **`/api`** prefix (e.g. `GET /api/papers`) so they never collide with frontend routes. `/docs`, `/openapi.json` and a root `/health` liveness probe stay at the root.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/run` | Trigger fetch + score + summarize cycle |
| `GET` | `/api/papers` | List papers (`?date=YYYY-MM-DD`, `?status=`, `?ids=a,b,c`, `?compact=true`) |
| `GET` | `/api/papers/search` | Search papers by title (`?q=query`, `?compact=true`) |
| `GET` | `/api/papers/{id}` | Get single paper details |
| `POST` | `/api/papers/add` | Add paper by arXiv ID or URL |
| `POST` | `/api/papers/{id}/resummarize` | Re-summarize a paper with LLM |
| `PATCH` | `/api/papers/{id}/score?score=N` | Set a manual score (overrides AI, disables re-scoring) |
| `POST` | `/api/papers/re-score-date?date=YYYY-MM-DD` | Re-score all papers for a date |
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
| `GET` | `/api/settings/llm` | Current models, thresholds, provider status |
| `PUT` | `/api/settings/llm` | Update `stage1_model` / `stage2_model` / `summary_model` / `stage2_threshold` / `score_threshold` |
| `GET` | `/api/models` | Provider model catalog with list prices (`?q=` filter, `?refresh=true`) |
| `GET` | `/api/llm/usage` | Real spend: today / 7d / 30d / all-time + per task/model breakdown |
| `GET` | `/api/llm/estimate` | Projected cost per day/month for a model selection (query params override current settings) |
| `GET` | `/api/papers/semantic-search?q=&limit=&days=&min_score=&category=&compact=` | Embedding search; returns papers with cosine `similarity` |
| `POST` | `/api/papers/semantic-search` | Agent-friendly search: `{"query"?, "paper_ids"? (seeds), "days"/"since"/"until", "min_score", "status", "category", "exclude_ids", "limit", "compact"}` |
| `GET` | `/api/papers/{id}/related?k=` | Nearest neighbours of a paper (`available=false` until it has a vector) |
| `GET` / `POST` | `/api/embeddings/status` · `/api/embeddings/backfill` · `/api/embeddings/reload` · `/api/embeddings/models` | Coverage, background backfill, index reload, embedding model list |
| `GET` | `/api/reports` · `/api/reports/{id}` | List (`?kind=daily\|weekly\|monthly`) / read trend reports |
| `POST` | `/api/reports/generate` | `{"kind": "weekly", "date": "YYYY-MM-DD"}` — generate or regenerate a report on demand (rate-limited) |
| `POST` / `DELETE` | `/api/reports/{id}/push` · `/api/reports/{id}` | Push a report to Lark / delete it |
| `WS` | `/api/ws/logs` | Live log stream (used by the in-app log viewer) |
| `GET` | `/health` · `/api/health` | Liveness probe |

---

## 🤝 MCP server (agents / Claude Code)

`mcp_server/` is a small separate package (`paper-agent-mcp`, stdio) with explicit tools over the API — see [`mcp_server/README.md`](mcp_server/README.md) for the tool list. Register it in Claude Code:

```bash
claude mcp add --scope user paper-agent -- uv run --directory /path/to/paper_agent/mcp_server paper-agent-mcp --base-url http://nas:8000
```

Typical asks: *"what did the people in my POI list publish this month"* (`papers_by_people`), *"papers from the last two weeks related to 2608.19556"* (`search_papers` with seeds), *"read 2608.18607 for me"* (`get_paper` with text), *"summarise this week's report"* (`list_reports` / `get_report`), *"mark 2608.18607 as 95, I read it"* (`set_user_score`).

---

## 🧪 Development

```bash
uv sync                                  # backend deps (Python 3.13)
uv run pytest -q                         # unit tests (in-memory SQLite, LLM calls mocked)
uv run uvicorn src.main:app --reload     # API on :8000 (serves frontend/dist if it exists)
cd frontend && npm install && npm run dev   # Vite dev server on :5173, proxies /api to :8000
cd frontend && npm run build             # production bundle -> frontend/dist
```

Layout: `src/main.py` (FastAPI routes), `src/worker.py` (fetch → two-stage score → summarize → notify), `src/services/` (arxiv, llm, pdf, notifier, model_catalog, settings_service, env_file, usage_service), `src/prompts/*.jinja2`, `src/migrations.py` (numbered, run automatically at startup), `frontend/src/` (React 19 + Vite + Tailwind). Docker image = `node` build stage for the frontend + `linuxserver/baseimage-alpine` + `uv`; pushing a `v*.*.*` tag publishes `harbory/paper-agent:<version>` and `:latest`, pushing `main` publishes `:dev`.

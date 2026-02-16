<p align="center">
  <h1 align="center">📄 Paper Agent</h1>
  <p align="center">
    <em>Your personal AI-powered arXiv digest — fetch, score, summarize, and browse daily papers effortlessly.</em>
  </p>
  <p align="center">
    <a href="https://github.com/HarborYuan/paper_agent/actions/workflows/docker-publish.yml"><img src="https://github.com/HarborYuan/paper_agent/actions/workflows/docker-publish.yml/badge.svg" alt="Docker Build"></a>
    <img src="https://img.shields.io/badge/version-0.2.0-cyan" alt="Version">
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
| 🤖 **LLM Scoring** | Scores papers against your research interests using GPT-4o-mini |
| 📝 **Smart Summaries** | Generates personalized markdown summaries with TL;DR, contributions, methodology |
| 📬 **Notifications** | Pushes daily digest to Lark (飞书) via webhook |
| 🌐 **Web UI** | Beautiful dark-theme interface with day-by-day infinite scroll |
| 🎚️ **Adjustable Threshold** | Filter papers by score with a live slider |
| 🔄 **Per-Paper Refresh** | Re-summarize any paper on demand |
| � **Author Rankings** | Browse top authors ranked by paper count with time-range filtering |
| �🐳 **Docker Ready** | Single-container deployment with LinuxServer.io-style config |

---


## 📋 Version History

| Version | Name | Highlights |
|---------|------|------------|
| **0.2.0** | *Authors Update* | Author ranking pages with time-range filter (7d/30d/90d/180d/360d/All) |
| **0.1.0** | *Notification Update* | Replaced Telegram/Pushover with Lark (飞书) webhook, date-grouped digests |
| **0.0.3** | *Beautify Update* | Markdown-rendered AI summaries, score threshold slider, per-paper refresh, README rewrite |
| **0.0.2** | — | Docker deployment, auto-update scheduler, WebSocket log viewer |
| **0.0.1** | — | Initial release: fetch, score, summarize, notify |

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
uv sync
```

### 2. Configure

Copy `.env.example` → `.env` and fill in your keys:

```env
DATABASE_URL="sqlite:///./paper_agent.db"
OPENAI_API_KEY="sk-..."

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
curl -X POST http://localhost:8000/run
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
| `OPENAI_API_KEY` | OpenAI API key | — |
| `ENABLE_AUTO_UPDATE` | Daily auto-fetch | `false` |
| `AUTO_UPDATE_TIME` | Fetch time (UTC) | `04:00` |

**Access:** Web UI at `http://localhost:8000` · API docs at `http://localhost:8000/docs`

---

## 📖 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/run` | Trigger fetch + score + summarize cycle |
| `GET` | `/papers` | List papers (optional `?date=YYYY-MM-DD`) |
| `GET` | `/papers/{id}` | Get single paper details |
| `POST` | `/papers/add` | Add paper by arXiv ID or URL |
| `POST` | `/papers/{id}/resummarize` | Re-summarize a paper with LLM |
| `POST` | `/papers/re-score-date` | Re-score all papers for a date |
| `GET` | `/authors` | Ranked author list (optional `?days=N`) |
| `GET` | `/authors/{name}/papers` | Papers by author (optional `?days=N`) |


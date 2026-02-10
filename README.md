# Paper Agent

[![Docker Build and Publish](https://github.com/HarborYuan/paper_agent/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/HarborYuan/paper_agent/actions/workflows/docker-publish.yml)

A FastAPI-based agent to fetch, score, summarize, and notify you about new arXiv papers daily.

## Features
- Fetches new papers from arXiv (De-duplicated)
- Scores papers using LLM (GPT-4o-mini) based on your interests
- Summarizes high-scoring papers
- Pushes daily digest to Telegram or Pushover
- **Web UI**: Day-by-day infinite scroll to browse papers by date

## Setup

1. **Install Dependencies**:
   ```bash
   uv sync
   ```

2. **Configuration**:
   Copy `.env.example` (or create `.env`) and fill in:
   ```bash
   DATABASE_URL="sqlite:///./paper_agent.db"
   OPENAI_API_KEY="sk-..."
   
   # Optional: Notifications
   TELEGRAM_BOT_TOKEN="..."
   TELEGRAM_CHAT_ID="..."
   # OR
   PUSHOVER_USER_KEY="..."
   PUSHOVER_API_TOKEN="..."
   ```

## Usage

1. **Start the API server**:
   ```bash
   uv run uvicorn src.main:app --reload
   ```

2. **Start the Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   Open [http://localhost:5173](http://localhost:5173).

3. **Trigger a Run Manually**:
   ```bash
   curl -X POST http://localhost:8000/run
   ```
   Check the server logs to see the progress (Fetching -> Scoring -> Summarizing -> Notifying).

3. **View Papers via API**:
   - Latest papers:
     ```bash
     curl http://localhost:8000/papers
     ```
   - Papers for a specific date:
     ```bash
     curl "http://localhost:8000/papers?date=2024-02-03"
     ```

## Docker Deployment (NAS / LinuxServer style)

This project supports a LinuxServer.io-style Docker deployment, running both the backend and frontend in a single container.

1. **Build the image**:
   ```bash
   docker build -t paper-agent .
   ```

2. **Run with Docker Compose**:
   Ensure your `docker-compose.yml` is configured (update environment variables as needed):
   ```bash
   docker-compose up -d
   ```

3. **Environment Variables**:
   - `PUID`/`PGID`: User/Group ID to run as (default 1000).
   - `DATABASE_URL`: Path to sqlite db (e.g. `sqlite:////config/paper_agent.db`).
   - `OPENAI_API_KEY`: Your OpenAI API key.

4. **Access**:
   - Web UI: http://localhost:8000
   - API Docs: http://localhost:8000/docs


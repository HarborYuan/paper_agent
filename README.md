# Paper Agent

A FastAPI-based agent to fetch, score, summarize, and notify you about new arXiv papers daily.

## Features
- Fetches new papers from arXiv (De-duplicated)
- Scores papers using LLM (GPT-4o-mini) based on your interests
- Summarizes high-scoring papers
- Pushes daily digest to Telegram or Pushover

## Setup

1. **Install Dependencies**:
   ```bash
   uv sync
   ```

2. **Configuration**:
   Copy `.env.example` (or create `.env`) and fill in:
   ```bash
   DATABASE_URL="postgresql+psycopg2://user:pass@localhost:5432/paper_agent_db"
   OPENAI_API_KEY="sk-..."
   
   # Optional: Notifications
   TELEGRAM_BOT_TOKEN="..."
   TELEGRAM_CHAT_ID="..."
   # OR
   PUSHOVER_USER_KEY="..."
   PUSHOVER_API_TOKEN="..."
   ```

3. **Database**:
   Ensure your PostgreSQL instance is running and the database exists. Tables are created automatically on app startup.

## Usage

1. **Start the API server**:
   ```bash
   uv run uvicorn src.main:app --reload
   ```

2. **Trigger a Run Manually**:
   ```bash
   curl -X POST http://localhost:8000/run
   ```
   Check the server logs to see the progress (Fetching -> Scoring -> Summarizing -> Notifying).

3. **View Papers via API**:
   ```bash
   curl http://localhost:8000/papers
   ```

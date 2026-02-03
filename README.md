# Paper Agent

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

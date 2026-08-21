# paper-agent-mcp

MCP server (stdio) that exposes a running [Paper Agent](..) instance to Claude Code / Claude Desktop / any MCP client.

## Tools

| Tool | What it does |
|---|---|
| `search_papers(query?, seed_ids?, days?, min_score?, status?, category?, exclude_ids?, limit)` | Semantic search (embeddings; any language; seeds = search near given papers) with filters |
| `search_titles(q, limit)` | Title substring search |
| `recent_papers(days=7, min_score=85, status?, category?, limit)` | What came out lately (digest set by default) |
| `related_papers(paper_id, k)` | Nearest neighbours of a paper |
| `get_paper(paper_id, include_text=false, max_text_chars)` | Full record: scores + rationale, personalised summary, optional PDF text |
| `get_papers(paper_ids)` | Compact records for many ids |
| `papers_by_people(names, days=30, min_score?, limit_per_author)` | People-of-interest lookup, fuzzy name matching |
| `mark_people_important(names, important=true)` | Flag people so their papers get a score boost |
| `list_reports(kind?, limit, with_content=false)` / `get_report(id)` | Daily / weekly / monthly trend reports |
| `set_user_score(paper_id, score)` | Write the user's judgement back (overrides AI score) |
| `add_paper(arxiv_id_or_url)` | Add + score + summarise a paper |
| `agent_status()` | Models, thresholds, embedding coverage |

## Run

```bash
# from the repo
uv run --directory mcp_server paper-agent-mcp --base-url http://nas:8000
# or without cloning
uvx --from "git+https://github.com/HarborYuan/paper_agent#subdirectory=mcp_server" paper-agent-mcp --base-url http://nas:8000
```

`PAPER_AGENT_URL` can replace `--base-url`.

## Claude Code

```bash
claude mcp add --scope user paper-agent -- uv run --directory /path/to/paper_agent/mcp_server paper-agent-mcp --base-url http://nas:8000
```

Then ask things like *"what did the people in my POI list publish this month"*, *"papers from the last two weeks related to 2608.19556"*, *"summarise this week's report"*, *"score 2608.18607 as 95, I read it"*.

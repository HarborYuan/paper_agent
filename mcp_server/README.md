# paper-agent-mcp

MCP server (stdio) that exposes a running [Paper Agent](..) instance to Claude Code / Claude Desktop / any MCP client.

## Tools

| Tool | What it does |
|---|---|
| `search_papers(query?, seed_ids?, days?, min_score?, status?, category?, exclude_ids?, limit)` | Semantic search (embeddings; any language; seeds = search near given papers) with filters |
| `search_titles(q, limit)` | Title substring search |
| `recent_papers(days=7, min_score=85, status?, category?, limit)` | What came out lately (digest set by default) |
| `related_papers(paper_id, k)` | Nearest neighbours of a paper |
| `get_paper(paper_id, include_text=false, max_text_chars)` | Full record: score + rationale (screen / review / deep read), TL;DR, optional PDF text |
| `get_papers(paper_ids)` | Compact records for many ids |
| `papers_by_people(names, days=30, min_score?, limit_per_author)` | People-of-interest lookup, fuzzy name matching |
| `mark_people_important(names, important=true)` | Flag people so their papers get a score boost |
| `deep_read_paper(paper_id, force=false)` | Start a deep read (real time, ~1-2 min): final verdict, TL;DR, paragraph gists, flagged claims, translation; returns the reading-page URL |
| `get_deep_read(paper_id, include_notes=false)` | Deep-read status, verdict and verified claim flags (optionally the paragraph gists) |
| `list_projects()` / `get_project(project, limit)` | Projects and the papers they collected (seed / manual / auto) |
| `create_project(name, description, keywords?, seed_paper_ids?)` / `update_project(project, …, active?)` | Create / edit a project; the description and seeds drive recall |
| `add_papers_to_project(project, paper_ids, as_seed=false)` / `remove_papers_from_project(project, paper_ids)` | Edit a project's papers |
| `project_suggestions(project, k)` | Library papers closest to a project, for backfilling |
| `set_user_score(paper_id, score)` | Write the user's judgement back (overrides AI score) |
| `add_paper(arxiv_id_or_url)` | Add a paper: screen, review and (if worth reading) deep read |
| `agent_status()` | Models, gates, Claude budget, embedding coverage |
| `get_bibtex(paper_ids?)` | BibTeX for any arXiv ids (`@inproceedings`/`booktitle` for conferences, `@article`/`journal` otherwise) + `needs_check`; no ids = whole library |
| `bibtex_venue_hints(paper_ids)` | Read-only: current arXiv comment / journal_ref / DOI, raw |
| `set_bibtex_status(paper_id, status, venue?, venue_type?, year?, evidence?)` | Write the agent's verdict back (venue stored as written) — `published` (final), `preprint` (re-flagged after 30 days), `unchecked` |
| `fix_bibtex(bibtex)` | Sync a pasted .bib with the library (no lookups): known-published preprints rewritten, keys kept; returns `needs_check` |

## Run

```bash
# from the repo
uv run --directory mcp_server paper-agent-mcp --base-url http://nas:8000
# or without cloning
uvx --from "git+https://github.com/HarborYuan/paper_agent#subdirectory=mcp_server" paper-agent-mcp --base-url http://nas:8000
```

`PAPER_AGENT_URL` can replace `--base-url`.

## Claude Code

Pinned to a release (recommended — independent of any checkout; the tag should match the server version):

```bash
claude mcp add --scope user paper-agent -- uvx --from "git+https://github.com/HarborYuan/paper_agent@v2.0.0#subdirectory=mcp_server" paper-agent-mcp --base-url http://nas:8000
```

To upgrade, `claude mcp remove paper-agent -s user` and add it again with the new tag. While developing the MCP server itself, run it from the checkout instead so edits apply on the next session:

```bash
claude mcp add --scope user paper-agent -- uv run --directory /path/to/paper_agent/mcp_server paper-agent-mcp --base-url http://nas:8000
```

Then ask things like *"what did the people in my POI list publish this month"*, *"papers from the last two weeks related to 2608.19556"*, *"deep-read 2611.23034"*, *"add these papers to my-tokenizer-project"*, *"score 2608.18607 as 95, I read it"*, *"give me the bibtex for 2408.00714"*, *"check which arXiv entries in main.bib have been accepted and fix them"*.

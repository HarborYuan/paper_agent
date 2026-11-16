---
name: fix-bib
description: One-shot clean-up of a .bib file with no server and no setup — the lightweight, stateless version of the Paper Agent's BibTeX workflow, meant for collaborators. Finds arXiv-preprint entries, checks whether each paper has since been published (arXiv comment, Semantic Scholar, then the web), rewrites the published ones, and strips every paper entry in the file down to four fields (title / author / booktitle-or-journal / year) — pages, volume, publisher, doi, url and the like are deleted — with the venue as a bare abbreviation: CVPR, ICCV, NIPS vs NeurIPS by year, IEEE TPAMI. Use when the user asks to fix / clean / update a .bib or references file ("fix bib", "replace the arXiv citations with the published versions", "unify the venues in the bib", "把 arXiv 的引用换成正式发表的", "修一下 bib").
---

# fix-bib — one-shot .bib fix, no server

Two jobs on one .bib: (1) find the preprint entries, verify now whether each paper has been
published, and give the published ones their venue; (2) clean every paper entry — delete the
fields that carry no information for a reference list (pages, url, doi, publisher, ...) and write
the venue as its abbreviation. Then check the result. Nothing is stored anywhere, so every run starts from zero.

There is no bundled script: this file is the specification. Write whatever throwaway code you
need (parsing, API calls, the checks in Step 5) in a temporary directory — never beside the .bib,
never committed to the user's repository.

If the session has the `mcp__paper-agent__*` tools **and they answer**, that is the full version
(it remembers verdicts) — use its `fix_bibtex` workflow instead of this skill.

## Step 1 — find the preprint entries

Parse the file properly (nested braces, `"..."` values, `#` concatenation; skip `@comment`,
`@string`, `@preamble`) rather than with line-based regexes.

An entry is a **preprint entry** when

- its type is not `book`, `inbook`, `phdthesis`, `mastersthesis`, `techreport` or `manual`, **and**
- its `journal` / `booktitle` is empty, or mentions `arXiv`, `CoRR` or `preprint`.

Its **arXiv id** (`NNNN.NNNNN`, version suffix dropped) is the `eprint` field when that is a bare
id; otherwise the first id found in `journal`, `booktitle`, `volume`, `url`, `doi`, `note`,
`howpublished`, `eprint`, `archiveprefix`, `publisher` — but only when those fields mention
`arXiv` or `CoRR` at all. A preprint entry with no id is handled by title (Step 2, last paragraph).

Everything else that is an `@inproceedings`, `@conference`, `@article` or `@incollection` with a
real venue is an **already-published entry**: no lookup needed, but it is cleaned in Step 4.

Entries of any other kind (`@book`, `@misc` for a website / dataset / software, `@techreport`,
theses, ...) are never touched — their `url` or `publisher` is the reference.

## Step 2 — collect evidence

Batch the lookups; do not make one request per paper where a batch call exists.

- **arXiv record** — `https://export.arxiv.org/api/query?id_list=<id1>,<id2>,...&max_results=<n>`
  (Atom XML, up to ~50 ids per call, wait 3 s between calls). Read `arxiv:comment`,
  `arxiv:journal_ref`, `arxiv:doi`: authors usually add "Accepted to CVPR 2026" with the
  camera-ready version. The API rate-limits bursts (HTTP 429 / timeouts): wait and retry once,
  then go on without it.
- **Semantic Scholar** — `POST https://api.semanticscholar.org/graph/v1/paper/batch?fields=title,venue,year,publicationVenue,journal,externalIds`
  with body `{"ids": ["ARXIV:<id>", ...]}` (no key needed, up to 500 ids, unknown ids come back
  as `null`). Gives a long venue name, its type (conference / journal), the year, and
  `externalIds.DBLP` / `externalIds.DOI`. Returns 429 in bursts: wait ~15 s and retry once.
- **OpenAlex** — `https://api.openalex.org/works?filter=title.search:<title>` (no key). Reports
  `type: preprint` vs a real venue. The fallback when Semantic Scholar is unavailable or silent.
- **The web** — OpenReview, the proceedings page, the publisher page, the project page.
- **DBLP** sits behind a bot challenge: do not script it and do not try to get past it.

Use a generic `User-Agent`; never put the user's name or email in a request.

Preprint entries without an arXiv id: search by exact title (OpenAlex, Semantic Scholar's
`/graph/v1/paper/search/match?query=<title>`, the web) and treat them like the others.

## Step 3 — decide

Evidence is a lead, not a verdict. Accept a paper as published when one of these holds:

- the arXiv `comment` / `journal_ref` says accepted / published / to appear at a named venue
  ("submitted to", "under review" are **not** acceptances);
- Semantic Scholar names a non-arXiv venue **and** something concrete backs it: a DBLP key that is
  not `journals/corr/...`, or a DOI that is not `10.48550/arXiv...`. Semantic Scholar alone gets
  workshop vs main conference and the year wrong often enough to need that second signal;
- a primary source on the web shows it (proceedings, OpenReview decision, publisher page).

Workshop papers are workshop papers ("CVPR Workshops"), not the main conference.

Bound the effort: check the unclear ones a few at a time in parallel; an entry that stays unclear
after a reasonable look **stays a preprint** and goes into the report. Never guess a venue.

## Venue naming — strict

The venue is printed exactly as written.

- **Conferences: always the bare abbreviation** — CVPR, ICCV, ECCV, NeurIPS, ICLR, ICML, ACL,
  EMNLP, NAACL, AAAI, IJCAI, WACV, BMVC, ACM MM, SIGGRAPH, KDD … Never "Proceedings of the IEEE/CVF
  Conference on Computer Vision and Pattern Recognition", never "IEEE/CVF CVPR", never "Proc.
  CVPR", never "CVPR 2026" (the year goes in `year`). Workshops: "CVPR Workshops"; findings:
  "Findings of EMNLP".
- **NIPS vs NeurIPS**: renamed in 2018. Year ≤ 2017 → `NIPS`; year ≥ 2018 → `NeurIPS`. Never
  "Advances in Neural Information Processing Systems".
- **Journals**: well-known ones by short name — IEEE TPAMI, IJCV, IEEE TIP, IEEE TMM, IEEE TCSVT,
  IEEE TNNLS, IEEE TVCG, IEEE RA-L, ACM TOG, JMLR, TMLR, TACL; any other journal by its full name.
- **Year** = the venue's year (ICLR 2025), not the arXiv upload year.

## Step 4 — rewrite and clean

Every paper entry ends up with **exactly four fields** — title, author, booktitle | journal, year:

```bibtex
@inproceedings{kirillov2023segment,
  title     = {Segment Anything},
  author    = {Kirillov, Alexander and Mintun, Eric and Ravi, Nikhila and Mao, Hanzi and Rolland, Chloe and Gustafson, Laura and Xiao, Tete and Whitehead, Spencer and Berg, Alexander C. and Lo, Wan-Yen and Doll{\'a}r, Piotr and Girshick, Ross},
  booktitle = {ICCV},
  year      = {2023}
}

@article{chen2024example,
  title   = {An Example},
  author  = {Chen, Ada},
  journal = {IEEE TPAMI},
  year    = {2024}
}

@article{doe2026draft,
  title   = {Still a Preprint},
  author  = {Doe, Jane},
  journal = {arXiv preprint arXiv:2601.01234},
  year    = {2026}
}
```

Which entries, and what happens to each:

| entry | venue | fields |
|---|---|---|
| preprint, now published (Step 3) | the verified venue and its year; type becomes `@inproceedings` / `@article` | cut to four |
| preprint with an arXiv id, still a preprint | `journal = {arXiv preprint arXiv:<id>}`, type `@article` — the id moves here, so nothing is lost when `eprint` / `url` go | cut to four |
| already-published entry | same venue, rewritten to the naming rules above (long name → abbreviation, year taken out of the venue, NIPS / NeurIPS by year); type corrected if it disagrees with the venue kind | cut to four |
| preprint entry with no arXiv id that could not be resolved | untouched | untouched |
| any other kind of entry | untouched | untouched |

**Delete, always**: pages, volume, number, month, publisher, organization, address, editor, series,
doi, url, eprint, archivePrefix, primaryClass, note, abstract, keywords, issn, isbn, file,
timestamp, biburl, bibsource — every field that is not one of the four. Do not ask first; this is
the point of the clean-up. Never paste publisher BibTeX (IEEE Xplore, ACM DL, DBLP, Google
Scholar) — take the venue and year from it, nothing else.

**Keep, always**:

- the cite key and the title text exactly as the entry had them (inner braces included, e.g.
  `{{Segment Anything}}` stays double-braced). The LaTeX sources cite these keys; do not "fix"
  title capitalisation;
- the author text as the entry had it — with one exception, below;
- the year of an already-published entry (change it only with evidence that it is wrong);
- every byte outside the paper entries: comments, `@string`, entry order, blank lines, line
  endings (a CRLF file stays CRLF), untouched entries.

**Authors of a paper that is now published — the official version wins.** The arXiv author list
can differ from the published one (authors added, names or order changed). When a reliable
official source gives the complete list — the proceedings or publisher page, the OpenReview
camera-ready, the publisher's BibTeX — and it differs from the entry, replace the author field
with the official list, in its order, as `Last, First and Last, First` (or the style the file
already uses). No such source, or only a truncated "et al." list → keep the entry's author text.
Never write authors from memory. Entries that stay preprints and already-published entries keep
their author text.

A venue you cannot map to an abbreviation with confidence (an unfamiliar long name, a `@string`
macro) keeps its text — still drop the extra fields, and list it in the report. Escape `&`, `%`,
`#` in venues you write.

Before writing: if the .bib is not tracked by git, or has uncommitted changes, copy the original
to the temporary directory first and tell the user where it is.

## Step 5 — verify (write the check yourself)

Do not report success from reading your own edit. Write a small throwaway check against the
original copy and the new file, run it, and fix what it finds:

1. Same cite keys, same order, same number of entries before and after.
2. Outside the paper entries, the two files are byte-identical; the untouched kinds of entry
   (`@book`, `@misc`, ...) are byte-identical too.
3. Every paper entry has exactly the four fields — list any entry that still has `pages`, `url`,
   `doi` or anything else — the right type for its venue kind, and title and author values
   identical to the original's, except the author fields you replaced with an official list
   (print those old → new and read them once more against the source).
4. No arXiv id was lost: every id present in the original still appears in the new file, unless
   that entry was given a published venue.
5. No venue contains `Proceedings`, `Conference`, `Symposium`, `Advances in`,
   `IEEE/CVF`, `Proc.` or a year; none of the well-known journals is spelled out;
   `NIPS` / `NeurIPS` agrees with the year on both sides of 2018.
6. Braces still balance, and the file still parses with the same parser used in Step 1.
7. If the .bib belongs to a LaTeX project that builds here, a build (or `bibtex` / `biber` run)
   shows no new warnings.

## Report

One short reply:

- changed: `cite_key` → venue year, with the evidence for each (URL or "arXiv comment"), and
  whether its author list was replaced by the official one (what changed);
- still preprints: checked and not published / unclear after checking (say which);
- cleaned: how many entries lost extra fields, and the venues that were renamed (old → new);
- preprint entries without an arXiv id that could not be resolved; venues left as written
  because no abbreviation was certain;
- which evidence sources were unavailable (rate limits), and what the Step 5 check covered.

"""Server-rendered bilingual reading page (/read/{paper_id}): original English units on the left,
the Chinese gist and full translation on the right, questionable / big claims highlighted in place."""
import html
from src.services.paper_views import summary_tldr
import json
import re
from typing import Dict, List, Optional

VL = {"must_read": "Must Read", "worth_reading": "Worth Reading", "skim": "Skim", "skip": "Skip"}
FK = {"questionable": ("Questionable", "q"), "big_claim": ("Big claim", "b")}
e = lambda s: html.escape(s or "", quote=True)
norm = lambda t: re.sub(r"\s+", " ", t or "").strip()

KATEX = """<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/contrib/auto-render.min.js"
 onload="renderMathInElement(document.body,{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}],throwOnError:false})"></script>"""

CSS = """
:root{--bg:#f7f6f2;--paper:#fffefb;--fg:#1f1f1d;--muted:#75746e;--line:#e6e3da;--soft:#f0eee7;--accent:#2b59c3;
--q:#c2410c;--qbg:#fde7d9;--b:#7c3aed;--bbg:#ede4fd;--good:#17803d;--warn:#a16207;--bad:#b91c1c;--zh:#fbfaf6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121212;--paper:#1a1a19;--fg:#e9e7e1;--muted:#9c9a93;--line:#2d2c29;--soft:#232220;--accent:#8fb0ff;
--q:#fb923c;--qbg:#4a2511;--b:#c4a5ff;--bbg:#33244f;--good:#4ade80;--warn:#facc15;--bad:#f87171;--zh:#1e1d1b}}
:root[data-theme="dark"]{--bg:#121212;--paper:#1a1a19;--fg:#e9e7e1;--muted:#9c9a93;--line:#2d2c29;--soft:#232220;--accent:#8fb0ff;
--q:#fb923c;--qbg:#4a2511;--b:#c4a5ff;--bbg:#33244f;--good:#4ade80;--warn:#facc15;--bad:#f87171;--zh:#1e1d1b}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Helvetica Neue",sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.top .in{max-width:1240px;margin:0 auto;padding:10px 24px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.top .crumb{font-size:14px;color:var(--muted);flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:999px;overflow:hidden;background:var(--paper)}
.seg label{padding:5px 13px;font-size:13px;cursor:pointer;color:var(--muted)}
input.mode{position:absolute;opacity:0;pointer-events:none}
#m-bi:checked~.top label[for=m-bi],#m-zh:checked~.top label[for=m-zh],#m-en:checked~.top label[for=m-en]{background:var(--fg);color:var(--bg)}
#m-zh:checked~main .en{display:none}#m-zh:checked~main .row{grid-template-columns:1fr}
#m-en:checked~main .zh{display:none}#m-en:checked~main .row{grid-template-columns:1fr}
main{max-width:1240px;margin:0 auto;padding:28px 24px 120px}
.hero{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:28px 32px;margin-bottom:28px}
.hero h1{font:600 28px/1.3 Georgia,"Times New Roman",serif;margin:6px 0 10px;letter-spacing:-.01em}
.kicker{font-size:13px;color:var(--muted);display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.authors{font-size:14.5px;line-height:1.6;margin-bottom:4px}.authors .more{color:var(--muted)}
.aff{font-size:13.5px;color:var(--muted);margin-bottom:14px}
.tldr{font-size:15.5px;line-height:1.75;margin:0 0 18px;padding:12px 16px;background:var(--soft);border-radius:10px}
.pill{display:inline-block;padding:2px 11px;border-radius:999px;font:600 12.5px/1.6 -apple-system,sans-serif;letter-spacing:.02em}
.must_read{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good)}
.worth_reading{background:color-mix(in srgb,var(--accent) 16%,transparent);color:var(--accent)}
.skim{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warn)}
.skip{background:color-mix(in srgb,var(--bad) 16%,transparent);color:var(--bad)}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.step{background:var(--soft);border-radius:10px;padding:12px 14px;font-size:13.5px;line-height:1.55}
.step .h{font-size:11.5px;font-weight:700;color:var(--muted);letter-spacing:.04em;margin-bottom:6px}
.step .d{color:var(--muted);font-size:12.5px;margin:4px 0}
.flagsum{margin-top:18px;font-size:14px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.flagsum a{font-size:13px;padding:2px 9px;border-radius:999px}
.flagsum a.q{background:var(--qbg);color:var(--q)}.flagsum a.b{background:var(--bbg);color:var(--b)}
h2.sec{font:600 22px/1.3 Georgia,serif;margin:46px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h3.sec{font:600 18px/1.35 Georgia,serif;margin:30px 0 10px}
h4.sec{font-size:15px;margin:22px 0 8px;color:var(--muted)}
.row{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);margin:0 0 14px;background:var(--paper);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.en{padding:16px 22px;font:15.5px/1.7 Georgia,"Times New Roman",serif}
.en p{margin:0 0 10px}.en p:last-child{margin-bottom:0}
.zh{padding:16px 22px;background:var(--zh);border-left:1px solid var(--line);font-size:15px;line-height:1.8}
.zh .gist{font-weight:600;margin:0 0 14px;padding-bottom:12px;border-bottom:1px dashed var(--line)}
.zh .tr{margin:0 0 10px;font-size:15px;line-height:1.85}
.zh .tr .cap{font-size:11px;font-weight:700;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 4px;margin-right:6px}
.tag{display:block;font:600 10.5px/1 -apple-system,sans-serif;color:var(--muted);letter-spacing:.08em;margin-bottom:8px}
mark{padding:1px 2px;border-radius:3px;color:inherit}
mark.q{background:var(--qbg);box-shadow:inset 0 -2px 0 var(--q)}mark.b{background:var(--bbg);box-shadow:inset 0 -2px 0 var(--b)}
sup.fn{font:700 11px -apple-system,sans-serif;margin-left:2px}sup.fn.q{color:var(--q)}sup.fn.b{color:var(--b)}
.callout{margin-top:12px;padding:10px 12px;border-radius:8px;font-size:14px;line-height:1.65}
.callout.q{background:var(--qbg);border-left:3px solid var(--q)}.callout.b{background:var(--bbg);border-left:3px solid var(--b)}
.callout .k{font-weight:700;margin-right:6px}.callout.q .k{color:var(--q)}.callout.b .k{color:var(--b)}
figure{margin:4px 0 12px;text-align:center}
figure img{max-width:100%;max-height:560px;border-radius:6px;background:#fff;border:1px solid var(--line)}
.fig{overflow-x:auto;background:#fff;border-radius:6px;border:1px solid var(--line);padding:8px}
.fig img,.fig object,.fig svg{max-width:100%;height:auto}.fig figure{margin:0}
figcaption,.tcap{font:14px/1.6 Georgia,serif;color:var(--muted);text-align:left;margin-top:8px}
.eq{overflow-x:auto;padding:6px 0;text-align:center}
.tbl{overflow-x:auto;font:12.5px/1.45 -apple-system,sans-serif;margin-top:6px}
.tbl table{border-collapse:collapse;margin:0 auto}.tbl img.tblimg{display:block;max-width:100%;margin:6px auto 0;background:#fff;border-radius:4px}
.tbl td,.tbl th{padding:3px 7px;border-bottom:1px solid var(--line);white-space:nowrap}
.tbl .ltx_border_t{border-top:1.5px solid var(--fg)}.tbl .ltx_border_b,.tbl .ltx_border_bb{border-bottom:1.5px solid var(--fg)}
.tbl .ltx_font_bold{font-weight:700}
.toc{position:fixed;left:max(8px,calc(50% - 620px - 240px));top:90px;width:210px;font-size:12.5px;line-height:1.5;max-height:calc(100vh - 120px);overflow:auto}
.toc a{display:block;color:var(--muted);padding:2px 0}.toc a.l3{padding-left:12px}
.summary{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:18px 24px;font-size:15px}
.summary h4{margin:16px 0 4px}
.notice{background:var(--paper);border:1px dashed var(--line);border-radius:12px;padding:20px 24px;color:var(--muted)}
@media (max-width:1720px){.toc{display:none}}
@media (max-width:860px){.row{grid-template-columns:1fr}.zh{border-left:0;border-top:1px solid var(--line)}main{padding:16px 16px 80px}
.hero{padding:20px 18px}.hero h1{font-size:22px}.steps{grid-template-columns:1fr}.top .in{padding:8px 16px}}
"""


def _highlight(text: str, flags: List[dict], fn_of: Dict[int, int]) -> str:
    spans = []
    for f in flags:
        sp = norm(f.get("span"))
        i = text.find(sp) if sp else -1
        if i >= 0:
            spans.append((i, i + len(sp), f))
    spans.sort(key=lambda x: x[0])
    out, pos = [], 0
    for a, b, f in spans:
        if a < pos:
            continue
        n, cls = fn_of[id(f)], FK[f["kind"]][1]
        out += [e(text[pos:a]), f"<mark class='{cls}' id='f{n}'>{e(text[a:b])}</mark><sup class='fn {cls}'>{n}</sup>"]
        pos = b
    out.append(e(text[pos:]))
    return "".join(out)


def _unit(u: dict, flags: List[dict], fn_of: Dict[int, int], fig_base: str) -> str:
    k = u["kind"]
    if k == "para":
        return f"<p>{_highlight(u['text'], flags, fn_of)}</p>"
    if k == "equation":
        return f"<div class='eq'>$${e(u['tex'])}$$</div>"
    if k == "figure":
        if u.get("crop"):
            body = f"<img loading='lazy' src='{fig_base}{e(u['crop'])}' alt=''>"
        elif u.get("html"):
            body = f"<div class='fig'>{u['html']}</div>"
        else:
            body = "".join(f"<img loading='lazy' src='{e(s)}' alt=''>" for s in u.get("srcs", [])[:2])
        return f"<figure>{body}<figcaption>{_highlight(u.get('caption', ''), flags, fn_of)}</figcaption></figure>"
    if k == "table":
        body = f"<img class='tblimg' loading='lazy' src='{fig_base}{e(u['crop'])}' alt=''>" if u.get("crop") else u.get("html", "")
        return f"<div class='tcap'>{_highlight(u.get('caption', ''), flags, fn_of)}</div><div class='tbl'>{body}</div>"
    return ""


def _md(text: str) -> str:
    out, lst = [], None
    for line in (text or "").splitlines():
        l = line.rstrip()
        h = re.match(r"^#{1,4}\s+(.*)", l)
        li = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.*)", l)
        if lst and not li:
            out.append(f"</{lst}>"); lst = None
        if h:
            out.append(f"<h4>{e(h.group(1))}</h4>")
        elif li:
            if not lst:
                lst = "ul"; out.append("<ul>")
            out.append(f"<li>{re.sub(r'[*][*](.+?)[*][*]', r'<b>\1</b>', e(li.group(1)))}</li>")
        elif l.strip():
            out.append(f"<p>{re.sub(r'[*][*](.+?)[*][*]', r'<b>\1</b>', e(l))}</p>")
    if lst:
        out.append(f"</{lst}>")
    return "\n".join(out)


def _projects(paper_id):
    try:
        from src.services import project_service
        return project_service.projects_of(paper_id)
    except Exception:
        return []


def render(paper, reading: Optional[dict], fig_base: str = "/api/figures/") -> str:
    reason = {}
    try:
        reason = json.loads(paper.score_reason) if paper.score_reason else {}
    except json.JSONDecodeError:
        pass
    s1, s2, deep = reason.get("stage1") or {}, reason.get("stage2") or {}, reason.get("deep") or {}
    if s2 and not s2.get("verdict") and not s2.get("error"):   # review from the old two-stage pipeline
        from src.services.verdict_pipeline import score_to_verdict
        s2 = {**s2, "verdict": score_to_verdict(s2.get("score")), "evidence": s2.get("quality", "–"), "reusability": "–"}
    final = deep or s2
    dims = lambda o: f"rel {o.get('relevance', '–')} · nov {o.get('novelty', '–')} · evi {o.get('evidence', '–')} · reuse {o.get('reusability', '–')}"
    pill = lambda v: f"<span class='pill {v}'>{VL.get(v, v)}</span>" if v else "<span class='d'>—</span>"
    authors = paper.authors_list
    authors_html = e(", ".join(authors[:14])) + (f" <span class='more'>+{len(authors) - 14} more</span>" if len(authors) > 14 else "")
    try:
        affs = json.loads(paper.affiliations) if paper.affiliations else []
    except json.JSONDecodeError:
        affs = []

    body, toc, flags_all = [], [], []
    if reading and reading.get("status") == "DONE" and reading.get("units"):
        units = reading["units"]
        by_id = {u["id"]: u for u in units}
        notes = reading.get("notes") or []
        tr = reading.get("translations") or {}
        note_of = {}
        for n in notes:
            for i in n.get("ids", []):
                note_of.setdefault(i, n)
        flags_all = [f for n in notes for f in n.get("flags", []) if f.get("verified")]
        fn_of = {id(f): k for k, f in enumerate(flags_all, 1)}
        emitted = set()
        for u in units:
            if u["kind"] == "heading":
                lvl = min(max(u.get("level", 2), 2), 4)
                hid = f"s-{u['id']}"
                body.append(f"<h{lvl} class='sec' id='{hid}'>{e(u['text'])}</h{lvl}>")
                if lvl <= 3:
                    toc.append(f"<a class='l{lvl}' href='#{hid}'>{e(u['text'])}</a>")
                continue
            n = note_of.get(u["id"])
            if n is None:
                zh = f"<p class='tr'>{e(tr[u['id']])}</p>" if u["id"] in tr else ""
                body.append(f"<div class='row'><div class='en'>{_unit(u, [], fn_of, fig_base)}</div><div class='zh'>{zh}</div></div>")
                continue
            if id(n) in emitted:
                continue
            emitted.add(id(n))
            fl = [f for f in n.get("flags", []) if f.get("verified")]
            en = "".join(_unit(by_id[i], [f for f in fl if f.get("id") == i], fn_of, fig_base) for i in n["ids"] if i in by_id)
            zh_tr = "".join(
                f"<p class='tr'>{('<span class=cap>' + ('Fig' if by_id[i]['kind'] == 'figure' else 'Table') + '</span>') if by_id[i]['kind'] in ('figure', 'table') else ''}{e(tr[i])}</p>"
                for i in n["ids"] if i in by_id and i in tr)
            call = "".join(f"<div class='callout {FK[f['kind']][1]}'><span class='k'>{fn_of[id(f)]} · {FK[f['kind']][0]}</span>{e(f.get('why'))}</div>" for f in fl)
            body.append(f"<div class='row'><div class='en'><span class='tag'>{' · '.join(n['ids'])}</span>{en}</div>"
                        f"<div class='zh'><span class='tag'>Summary</span><p class='gist'>{e(n.get('gist'))}</p>"
                        f"{'<span class=tag>Translation</span>' + zh_tr if zh_tr else ''}{call}</div></div>")
    else:
        status = (reading or {}).get("status")
        msg = {"RUNNING": "Deep read in progress — refresh in a minute or two.",
               "PENDING": "Deep read queued.",
               "ERROR": f"Deep read failed: {e((reading or {}).get('error'))}"}.get(status, "No deep read yet. Trigger one from the paper page or the MCP tool <code>deep_read_paper</code>.")
        body.append(f"<div class='notice'>{msg}</div>")
        if reading and reading.get("status") == "DONE" and not reading.get("units"):
            body.insert(0, "<div class='notice'>This paper has no arXiv HTML version, so there is no paragraph-by-paragraph reading; the summary is below.</div>")

    nq = sum(f["kind"] == "questionable" for f in flags_all)
    links = "".join(f"<a class='{FK[f['kind']][1]}' href='#f{k}'>{k} {FK[f['kind']][0]}</a>" for k, f in enumerate(flags_all, 1))
    flagsum = f"<div class='flagsum'><b>{len(flags_all)} flags</b>(Questionable {nq} · Big claim {len(flags_all) - nq}){links}</div>" if flags_all else ""
    change = f"<div class='d'>Revised: {e(deep.get('verdict_change_reason'))}</div>" if deep.get("verdict_change_reason") else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(paper.title[:80])}</title><style>{CSS}</style>{KATEX}</head><body>
<input class="mode" type="radio" name="m" id="m-bi" checked><input class="mode" type="radio" name="m" id="m-zh"><input class="mode" type="radio" name="m" id="m-en">
<div class="top"><div class="in"><a href="/paper/{e(paper.id)}">← Paper</a><span class="crumb">{e(paper.title)}</span>
<span class="seg"><label for="m-bi">Bilingual</label><label for="m-zh">Chinese</label><label for="m-en">English</label></span></div></div>
<nav class="toc">{''.join(toc)}</nav>
<main>
<section class="hero">
<div class="kicker">{pill(final.get('verdict'))}<a href="https://arxiv.org/abs/{e(paper.id)}">arXiv {e(paper.id)}</a><a href="https://arxiv.org/pdf/{e(paper.id)}">PDF</a><a href="https://arxiv.org/html/{e(paper.id)}">HTML</a><span>score {paper.score if paper.score is not None else '–'}</span></div>
<h1>{e(paper.title)}</h1>
<div class="authors">{authors_html}</div>
<div class="aff">{e(' · '.join(affs))}</div>
{('<div class="kicker" style="margin:-8px 0 14px">' + ''.join(f'<a class="pill worth_reading" href="/projects">{e(n)}</a>' for n in _projects(paper.id)) + '</div>') if _projects(paper.id) else ''}
{f'<p class="tldr">{e(summary_tldr(paper.summary_personalized, 600))}</p>' if paper.summary_personalized else ''}
<div class="steps">
<div class="step"><div class="h">① Screen · {e(s1.get('model', ''))}</div>relevance <b>{s1.get('relevance', '–')}</b> · {e(s1.get('matched_section', ''))}<div class="d">{e(s1.get('one_line_reason'))}</div></div>
<div class="step"><div class="h">② Review · first part</div>{pill(s2.get('verdict'))}<div class="d">{dims(s2) if s2 else ''}</div><div class="d">{e(s2.get('one_line_reason'))}</div></div>
<div class="step"><div class="h">③ Deep read · full text</div>{pill(deep.get('verdict'))}<div class="d">{dims(deep) if deep else ''}</div><div class="d">{e(deep.get('one_line_reason'))}</div>{change}</div>
</div>
{flagsum}
</section>
{''.join(body)}
</main></body></html>"""


PICKS_CSS = """
.day{font:600 20px Georgia,serif;margin:34px 0 12px;display:flex;align-items:baseline;gap:10px}
.day small{font:13px -apple-system,sans-serif;color:var(--muted)}
.pick{display:block;background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:18px 22px;margin:0 0 12px;color:var(--fg)}
.pick:hover{border-color:var(--accent);text-decoration:none}
.pick h3{font:600 18px/1.4 Georgia,serif;margin:6px 0 4px}
.pick .meta{font-size:13px;color:var(--muted)}
.pick .tl{font-size:15px;line-height:1.75;margin:8px 0 6px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.chip{font-size:12px;padding:1px 8px;border-radius:999px;background:var(--soft);color:var(--muted)}
.chip.q{background:var(--qbg);color:var(--q)}.chip.b{background:var(--bbg);color:var(--b)}.chip.p{background:color-mix(in srgb,var(--accent) 12%,transparent);color:var(--accent)}
.pager{display:flex;justify-content:space-between;margin-top:30px;font-size:14px}
"""


def render_picks(days: List[tuple], readings: Dict[str, dict], projects: Dict[str, List[str]],
                 prev_date: Optional[str], next_date: Optional[str], title: str) -> str:
    """days: [(date_str, [Paper, ...])]; readings: {paper_id: {"status", "flags": {"q": n, "b": n}}}."""
    blocks = []
    for day, papers in days:
        cards = []
        for p in papers:
            try:
                r = json.loads(p.score_reason) if p.score_reason else {}
            except json.JSONDecodeError:
                r = {}
            fin = r.get("deep") or r.get("stage2") or {}
            v = fin.get("verdict")
            au = p.authors_list
            authors = ", ".join(au[:4]) + (f" +{len(au) - 4}" if len(au) > 4 else "")
            rd = readings.get(p.id) or {}
            chips = []
            if rd.get("status") == "DONE":
                chips.append("<span class='chip'>reading page</span>")
            fl = rd.get("flags") or {}
            if fl.get("q"):
                chips.append(f"<span class='chip q'>{fl['q']} questionable</span>")
            if fl.get("b"):
                chips.append(f"<span class='chip b'>{fl['b']} big claim</span>")
            chips += [f"<span class='chip p'>{e(n)}</span>" for n in projects.get(p.id, [])]
            tl = summary_tldr(p.summary_personalized, 400) if p.summary_personalized else fin.get("one_line_reason", "")
            cards.append(f"""<a class="pick" href="/read/{e(p.id)}"><span class="pill {v or ''}">{VL.get(v, '–')}</span>
<span class="meta"> &nbsp;{e(p.id)} · {e(p.main_affiliation or '')}</span>
<h3>{e(p.title)}</h3><div class="meta">{e(authors)}</div><div class="tl">{e(tl)}</div><div class="chips">{''.join(chips)}</div></a>""")
        blocks.append(f"<div class='day'>{e(day)} <small>{len(papers)} picks</small></div>" + "".join(cards))
    if not blocks:
        blocks.append("<div class='notice'>No Must Read / Worth Reading papers in this range yet.</div>")
    pager = "<div class='pager'>" + (f"<a href='/picks?date={prev_date}'>← Earlier</a>" if prev_date else "<span></span>") \
        + (f"<a href='/picks?date={next_date}'>Later →</a>" if next_date else "<span></span>") + "</div>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}{PICKS_CSS}</style></head><body>
<div class="top"><div class="in"><a href="/">← Digest</a><span class="crumb">{e(title)}</span><a href="/projects">Projects</a></div></div>
<main style="max-width:900px">
<div class="hero"><h1>Daily Picks</h1><div class="kicker">Must Read and Worth Reading papers by publication date · open one for the bilingual reading page</div></div>
{''.join(blocks)}{pager}
</main></body></html>"""

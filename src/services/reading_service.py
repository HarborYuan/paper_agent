"""
Reading units for the deep read and the /read page.

1. segment(): split an arXiv HTML (LaTeXML) paper into ordered units — heading / para / equation /
   figure / table — with ids P#, E#, F#, T#, stopping at the appendix and bibliography.
2. Figures and tables that LaTeXML renders badly (TikZ drawn as inline SVG, tables scaled with
   \\resizebox, tables containing TikZ) are cropped from the PDF by their caption and stored as WebP
   under FIGURE_DIR; every other figure keeps its arXiv URL (nothing else is stored locally).
"""
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from src.config import settings

UA = {"User-Agent": "paper-agent (https://github.com/HarborYuan/paper_agent)"}


# ---------------------------------------------------------------------------- HTML -> units
def _media(node) -> List[str]:
    """Image sources in a node: <img src> and <object data> (LaTeXML embeds SVG plots that way)."""
    out = []
    for m in node.find_all(["img", "object"]):
        src = m.get("src") if m.name == "img" else m.get("data")
        if src and "static.arxiv.org" not in src and not src.endswith("arxiv-logo.svg"):
            out.append(src)
    return out


def _abs_html(node, base_url: str, drop_caption: bool = False) -> str:
    """Original markup with relative media URLs made absolute; caption optionally removed."""
    node = BeautifulSoup(str(node), "html.parser")
    if drop_caption:
        for c in node.find_all("figcaption"):
            c.decompose()
    for t in node.find_all(True):
        for attr in ("src", "data", "href", "xlink:href"):
            v = t.get(attr)
            if v and not v.startswith(("http", "#", "data:", "mailto:")):
                t[attr] = urljoin(base_url, v)
    return str(node)


def _text(node) -> str:
    """Inline text with math as $alttext$, footnotes dropped, whitespace collapsed."""
    out: List[str] = []

    def walk(n):
        if isinstance(n, NavigableString):
            out.append(str(n))
            return
        if not isinstance(n, Tag):
            return
        cls = n.get("class") or []
        if n.name == "math":
            alt = n.get("alttext") or ""
            out.append(f"${alt}$" if alt else "")
            return
        if "ltx_note" in cls or n.name in ("script", "style", "figure") or "ltx_tag_equation" in cls \
                or "ltx_tag_bibitem" in cls:
            return
        for c in n.children:
            walk(c)

    walk(node)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def needs_crop(unit: dict) -> bool:
    """Figures/tables whose LaTeXML rendering is unreliable (TikZ / scaled tables)."""
    html = unit.get("html") or ""
    if unit["kind"] == "figure":
        return "<svg" in html
    if unit["kind"] == "table":
        return "<svg" in html or "ltx_transformed" in html
    return False


def segment(html: str, base_url: str) -> List[dict]:
    soup = BeautifulSoup(html, "html.parser")
    art = soup.find("article") or soup
    units: List[dict] = []
    counters = {"P": 0, "E": 0, "F": 0, "T": 0}
    section = "Abstract"

    def add(kind, prefix, **kw):
        counters[prefix] += 1
        u = {"id": f"{prefix}{counters[prefix]}", "kind": kind, "section": section, **kw}
        units.append(u)
        return u

    abstract = art.find(class_="ltx_abstract")
    if abstract:
        units.append({"id": "H0", "kind": "heading", "level": 2, "text": "Abstract", "section": "Abstract"})
        for p in abstract.find_all("p", class_="ltx_p"):
            t = _text(p)
            if t:
                add("para", "P", text=t)

    # LaTeXML sometimes breaks a paper: the reference list lands mid-section and the sections after it
    # carry their text in stray bibliography items. Read past it and keep that text as paragraphs.
    broken = any(not li.find_parent(class_="ltx_bibliography") for li in art.find_all("li", class_="ltx_bibitem"))

    seen = set()
    for el in art.find_all(True):
        if any(id(a) in seen for a in el.parents):
            continue
        cls = el.get("class") or []
        if "ltx_appendix" in cls or ("ltx_bibliography" in cls and not broken):
            break
        if broken and "ltx_title_bibliography" in cls:
            seen.add(id(el))
            continue
        if broken and el.name == "li" and "ltx_bibitem" in cls:
            for blk in el.find_all("span", class_="ltx_bibblock", recursive=False):
                blk = BeautifulSoup(str(blk), "html.parser")
                for nested in blk.find_all("li"):
                    nested.decompose()       # visited on its own
                t = _text(blk)
                if t and len(t) > 1:
                    add("para", "P", text=t)
            continue
        if abstract is not None and (el is abstract or abstract in el.parents):
            continue
        if el.name in ("h2", "h3", "h4", "h5") and "ltx_title" in cls \
                and "ltx_title_document" not in cls and "ltx_title_abstract" not in cls:
            t = _text(el)
            if t:
                section = t
                units.append({"id": f"H{len(units)}", "kind": "heading", "level": int(el.name[1]), "text": t, "section": t})
            seen.add(id(el))
            continue
        if el.name == "figure" and ("ltx_figure" in cls or "ltx_table" in cls):
            cap = el.find("figcaption")
            caption = _text(cap) if cap else ""
            if "ltx_table" in cls:
                # keep the whole float (minus caption): \resizebox wrappers sit outside the <table>
                add("table", "T", caption=caption, html=_abs_html(el, base_url, drop_caption=True) if el.find("table") else "")
            else:
                imgs = _media(el)
                if not imgs:  # e.g. a teaser whose image sits in the paragraph right before the <figure>
                    for sib in el.find_previous_siblings(limit=2):
                        imgs = _media(sib) if isinstance(sib, Tag) else []
                        if imgs:
                            break
                has_own = bool(el.find(["img", "object", "svg"]))
                add("figure", "F", caption=caption, srcs=[urljoin(base_url, s) for s in imgs][:4],
                    html=_abs_html(el, base_url, drop_caption=True) if has_own else "")
            seen.add(id(el))
            continue
        if el.name == "table" and ("ltx_equation" in " ".join(cls) or "ltx_eqn_table" in cls):
            maths = [m.get("alttext") for m in el.find_all("math") if m.get("alttext")]
            if maths:
                add("equation", "E", tex=" ".join(maths))
            seen.add(id(el))
            continue
        if el.name == "p" and "ltx_p" in cls:
            t = _text(el)
            if t and len(t) > 1:
                add("para", "P", text=t)
            seen.add(id(el))
    for u in units:
        if u["kind"] == "table":
            u["table_text"] = re.sub(r"\s+", " ", BeautifulSoup(u["html"], "html.parser").get_text(" "))[:2000]
    return units


# ---------------------------------------------------------------------------- PDF crops
def _lines(page) -> List[dict]:
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            spans = [sp for sp in l["spans"] if sp["text"].strip()]
            if spans:
                import pymupdf
                text = re.sub(r"\s+", " ", "".join(sp["text"] for sp in l["spans"])).strip()
                out.append({"r": pymupdf.Rect(l["bbox"]), "t": text,
                            "font": (spans[0]["font"], round(spans[0]["size"], 1))})
    out.sort(key=lambda x: (x["r"].y0, x["r"].x0))
    return out


def _doc_font(doc):
    """The running-text font: the one carrying the most characters in the document."""
    fc = Counter()
    for p in doc:
        for l in _lines(p):
            fc[l["font"]] += len(l["t"])
    return fc.most_common(1)[0][0] if fc else None


def _is_body(line: dict, body_font) -> bool:
    if body_font is not None and line["font"] != body_font:
        return False
    t = line["t"]
    digits = sum(c.isdigit() for c in t) / max(1, len(t))
    return len(t) > 45 and digits < 0.12


def _caption(lines, kind, num):
    pat = re.compile(rf"^\s*{kind}\s*{re.escape(num)}\s*[:.]")
    k = next((i for i, l in enumerate(lines) if pat.match(l["t"])), None)
    if k is None:
        return None, None
    cap = lines[k]["r"] + (0, 0, 0, 0)
    font = lines[k]["font"]
    ids = {k}
    first = lines[k]["r"]
    same_col = lambda r: min(r.x1, first.x1) - max(r.x0, first.x0) > 0.5 * min(r.width, first.width)
    for i in range(k + 1, len(lines)):
        r = lines[i]["r"]
        if not same_col(r):
            continue
        if lines[i]["font"] == font and 0 <= r.y0 - cap.y1 < 6:
            cap |= r
            ids.add(i)
        elif r.y0 > cap.y1 + 6:
            break
    return cap, ids


def crop_figure(doc, label: str):
    """Pixmap of the figure above its caption ("Figure 3"), or None."""
    import pymupdf
    kind, num = label.split()[0], label.split()[-1]
    for page in doc:
        lines = _lines(page)
        cap, _ = _caption(lines, kind, num)
        if cap is None:
            continue
        rects = [pymupdf.Rect(d["rect"]) for d in page.get_drawings()] + [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
        rects = [r for r in rects if r.y1 <= cap.y0 + 2 and r.height < page.rect.height * 0.9 and r.width > 1]
        rects.sort(key=lambda r: -r.y1)
        top, region = cap.y0, None
        for r in rects:
            if r.y1 < top - 40:
                break
            region = r if region is None else region | r
            top = min(top, r.y0)
        if region is None:
            return None
        for l in lines:
            if l["r"].y0 >= region.y0 - 12 and l["r"].y1 <= cap.y0 + 1 and len(l["t"]) < 200 \
                    and min(l["r"].x1, region.x1 + 80) > max(l["r"].x0, region.x0 - 80):
                region |= l["r"]
        clip = pymupdf.Rect(region.x0 - 6, region.y0 - 6, region.x1 + 6, cap.y0 - 2) & page.rect
        return page.get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5), clip=clip)
    return None


def crop_table(doc, label: str, body_font=None):
    """Pixmap of the table attached to its caption ("Table 2"), caption above or below; or None."""
    import pymupdf
    kind, num = label.split()[0], label.split()[-1]
    for page in doc:
        lines = _lines(page)
        cap, cap_ids = _caption(lines, kind, num)
        if cap is None:
            continue
        page_x0 = min(l["r"].x0 for l in lines)
        page_x1 = max(l["r"].x1 for l in lines)
        if cap.width < 0.6 * (page_x1 - page_x0):   # two-column layout: stay in the caption's column
            mid = (page_x0 + page_x1) / 2
            band = (page_x0, mid) if cap.x1 <= mid + 5 else (mid, page_x1)
        else:
            band = (page_x0, page_x1)
        inside = lambda r: r.x0 >= band[0] - 8 and r.x1 <= band[1] + 8
        rules = [pymupdf.Rect(d["rect"]) for d in page.get_drawings() if pymupdf.Rect(d["rect"]).width > 20]
        items = [("rule", r) for r in rules if inside(r)] + \
                [("text", l) for i, l in enumerate(lines) if i not in cap_ids and inside(l["r"])]
        rect = lambda it: it[1] if it[0] == "rule" else it[1]["r"]
        below = sorted([it for it in items if rect(it).y0 >= cap.y1 - 1], key=lambda it: rect(it).y0)
        above = sorted([it for it in items if rect(it).y1 <= cap.y0 + 1], key=lambda it: -rect(it).y1)

        def first_rule_gap(seq, down):
            for it in seq:
                if it[0] == "rule":
                    return (rect(it).y0 - cap.y1) if down else (cap.y0 - rect(it).y1)
                if _is_body(it[1], body_font):
                    return 1e9
            return 1e9

        down = first_rule_gap(below, True) <= first_rule_gap(above, False)
        region, edge, seen_rule = None, (cap.y1 if down else cap.y0), False
        for it in (below if down else above):
            r = rect(it)
            if not seen_rule and it[0] == "text" and not _is_body(it[1], body_font):
                edge = max(edge, r.y1) if down else min(edge, r.y0)
                continue  # caption continuation before the first rule
            seen_rule = seen_rule or it[0] == "rule"
            gap = (r.y0 - edge) if down else (edge - r.y1)
            if gap > 28 or (it[0] == "text" and (_is_body(it[1], body_font)
                                                 or re.match(r"^\s*(Table|Figure)\s+\d+\s*[:.]", it[1]["t"]))):
                break
            region = pymupdf.Rect(r) if region is None else region | r
            edge = max(edge, r.y1) if down else min(edge, r.y0)
        if region is None:
            return None
        clip = pymupdf.Rect(region.x0 - 6, region.y0 - 4, region.x1 + 6, region.y1 + 4) & page.rect
        return page.get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5), clip=clip)
    return None


def _save_webp(pix, path: Path) -> None:
    from PIL import Image
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "WEBP", quality=85)


def crop_units(paper_id: str, units: List[dict], pdf_bytes: Optional[bytes]) -> int:
    """Crop the units that need it from the PDF; sets unit["crop"] to a file name in FIGURE_DIR."""
    todo = [u for u in units if needs_crop(u)]
    if not todo or not pdf_bytes:
        return 0
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    body_font = _doc_font(doc)
    n = 0
    for u in todo:
        m = re.match(r"^\s*(Figure|Table)\s*([A-Z]?\d+)", u.get("caption") or "")
        if not m:
            continue
        label = f"{m.group(1)} {m.group(2)}"
        try:
            pix = crop_figure(doc, label) if u["kind"] == "figure" else crop_table(doc, label, body_font)
        except Exception as e:  # a bad crop must not break the read
            print(f"  - crop {paper_id} {label} failed: {e}")
            pix = None
        if pix is not None and pix.width > 40 and pix.height > 20:
            name = f"{paper_id.replace('/', '_')}-{u['id']}.webp"
            _save_webp(pix, Path(settings.figure_dir) / name)
            u["crop"] = name
            n += 1
    return n


# ---------------------------------------------------------------------------- fetch
async def fetch_units(paper_id: str, pdf_url: Optional[str] = None) -> Optional[List[dict]]:
    """arXiv HTML -> units, with broken figures/tables cropped from the PDF. None if no HTML version."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=60, headers=UA) as c:
        try:
            r = await c.get(f"https://arxiv.org/html/{paper_id}")
        except httpx.HTTPError:
            return None   # the caller falls back to the PDF text
        if r.status_code != 200 or "ltx_document" not in r.text:
            return None
        units = segment(r.text, str(r.url))
        if not any(u["kind"] == "para" for u in units):
            return None
        if any(needs_crop(u) for u in units):
            try:
                pr = await c.get(pdf_url or f"https://arxiv.org/pdf/{paper_id}")
                pdf = pr.content if pr.status_code == 200 and pr.content[:4] == b"%PDF" else None
            except httpx.HTTPError:
                pdf = None
            try:
                crop_units(paper_id, units, pdf)
            except Exception as e:  # an unreadable PDF leaves the HTML figures as they are
                print(f"  - crops for {paper_id} failed: {e}")
    return units


def dumps(units) -> str:
    return json.dumps(units, ensure_ascii=False)

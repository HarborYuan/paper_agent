"""BibTeX library: agent-driven venue verdicts (stored as given), entry types, 30-day recheck, hints, .bib sync."""
from datetime import datetime, timedelta

import pytest
from sqlmodel import SQLModel, Session, StaticPool, create_engine

from src.models import BibEntry, Paper
from src.services import bibtex_service as b
from src.services.arxiv import ArxivAPIError


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _meta(pid, title="Great Model for Video", authors=("Haobo Yuan", "Ming-Hsuan Yang"), comment=None,
          journal_ref=None):
    return {"id": pid, "title": title, "authors": list(authors), "comment": comment, "journal_ref": journal_ref,
            "doi": None, "published": datetime(2026, 2, 1), "updated": datetime(2026, 3, 1)}


class Arxiv:
    """Fake arXiv API patched into bibtex_service. The server must not call anything else."""

    def __init__(self, monkeypatch):
        self.meta, self.down, self.calls = {}, False, []
        monkeypatch.setattr(b, "fetch_metadata", self._fetch)

    def _fetch(self, ids, retry_delays=None):
        self.calls.append(list(ids))
        if self.down:
            raise ArxivAPIError("down")
        return {i: self.meta[i] for i in ids if i in self.meta}


# ---------------------------------------------------------------------------
# Rendering / keys
# ---------------------------------------------------------------------------
def test_cite_key():
    assert b.base_cite_key(["Piotr Dollár"], 2026, "Towards Better Segmentation") == "dollar2026better"
    assert b.base_cite_key([], 2026, "SAM 2: Segment") == "anon2026sam"
    assert b.arxiv_year("2408.00714") == 2024 and b.arxiv_year("cs/9912001") == 1999


def test_render_by_type(session, monkeypatch):
    ax = Arxiv(monkeypatch)
    ax.meta["2602.00001"] = _meta("2602.00001", title="Seg & Track: 100% Better")
    e = b.get_entries(session, ["https://arxiv.org/abs/2602.00001v3"])["entries"][0]
    assert b.render(e) == (
        "@article{yuan2026seg,\n"
        "  title   = {{Seg \\& Track: 100\\% Better}},\n"
        "  author  = {Haobo Yuan and Ming-Hsuan Yang},\n"
        "  journal = {arXiv preprint arXiv:2602.00001},\n"
        "  year    = {2026}\n"
        "}")
    e = b.set_status(session, "2602.00001", "published", "CVPR", "conference", 2027)
    assert b.render(e) == (
        "@inproceedings{yuan2026seg,\n"
        "  title     = {{Seg \\& Track: 100\\% Better}},\n"
        "  author    = {Haobo Yuan and Ming-Hsuan Yang},\n"
        "  booktitle = {CVPR},\n"
        "  year      = {2027}\n"
        "}")
    e = b.set_status(session, "2602.00001", "published", "Pattern  Recognition", "journal", 2028)
    assert "@article{yuan2026seg," in b.render(e) and "  journal = {Pattern Recognition},\n  year    = {2028}" in b.render(e)
    assert e.cite_key == "yuan2026seg"   # key never changes


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------
def test_get_entries_creates_unchecked_without_lookup(session, monkeypatch):
    ax = Arxiv(monkeypatch)
    ax.meta["2602.00001"] = _meta("2602.00001", comment="Accepted to CVPR 2026")
    ax.meta["2602.00002"] = _meta("2602.00002")
    res = b.get_entries(session, ["2602.00001", "2602.00002", "2602.99999"])
    e1, e2 = res["entries"]
    # Even with an "Accepted to" comment nothing is applied automatically — the agent decides
    assert (e1.status, e1.venue, b.needs_check(e1)) == ("unchecked", None, True)
    assert (e1.cite_key, e2.cite_key) == ("yuan2026great", "yuan2026greatb")
    assert res["missing"] == ["2602.99999"]
    ax.calls.clear()
    b.get_entries(session, ["2602.00001"])
    assert ax.calls == []   # already in the library


def test_get_entries_falls_back_to_local_paper_when_arxiv_down(session, monkeypatch):
    ax = Arxiv(monkeypatch)
    ax.down = True
    session.add(Paper(id="2601.00005", title="Local  Title", authors='["Jane Doe"]', summary_generic="",
                      published_at=datetime(2026, 1, 5), category_primary="cs.CV", all_categories="[]", pdf_url=""))
    session.commit()
    res = b.get_entries(session, ["2601.00005"])
    assert res["entries"][0].title == "Local Title" and res["entries"][0].cite_key == "doe2026local"
    assert res["warnings"]


def test_needs_check_lifecycle(session, monkeypatch):
    ax = Arxiv(monkeypatch)
    ax.meta["2602.00001"] = _meta("2602.00001")
    b.get_entries(session, ["2602.00001"])
    e = b.set_status(session, "2602.00001", "preprint", evidence="no acceptance on DBLP / OpenReview")
    assert e.status == "preprint" and not b.needs_check(e)
    assert b.needs_check(e, now=datetime.now() + timedelta(days=b.RECHECK_DAYS + 1))
    e = b.set_status(session, "2602.00001", "published", "NeurIPS", "conference", 2026, evidence="https://openreview.net/x")
    assert not b.needs_check(e, now=datetime.now() + timedelta(days=3650))   # published is final
    e = b.set_status(session, "2602.00001", "unchecked")
    assert (e.venue, e.evidence, e.checked_at, b.needs_check(e)) == (None, None, None, True)


def test_set_status_validation_and_create(session, monkeypatch):
    ax = Arxiv(monkeypatch)
    ax.meta["2602.00003"] = _meta("2602.00003")
    with pytest.raises(b.BibUpdateError):
        b.set_status(session, "2602.00003", "published", "CVPR", "conference")   # no year
    with pytest.raises(b.BibUpdateError, match="venue_type"):
        b.set_status(session, "2602.00003", "published", "CVPR", year=2026)       # no type
    with pytest.raises(b.BibUpdateError, match="venue_type"):
        b.set_status(session, "2602.00003", "published", "CVPR", "workshop", 2026)
    with pytest.raises(b.BibUpdateError):
        b.set_status(session, "2602.00003", "accepted")
    # Stored exactly as the agent wrote it — no normalisation
    name = "International Conference on Computer Vision Theory and Applications"
    e = b.set_status(session, "2602.00003", "published", name, "conference", 2026)
    assert (e.venue, e.venue_type) == (name, "conference")                       # created on the fly
    with pytest.raises(LookupError):
        b.set_status(session, "2602.99999", "preprint")


def test_hints_are_read_only(session, monkeypatch):
    ax = Arxiv(monkeypatch)
    ax.meta["2602.00001"] = _meta("2602.00001")
    b.get_entries(session, ["2602.00001"])
    ax.meta["2602.00001"] = _meta("2602.00001", title="Great Model for Video (camera-ready)",
                                  comment="Accepted to ICLR 2027. Code: https://github.com/x")
    [h] = b.hints(session, ["2602.00001"])
    assert h["comment"] == "Accepted to ICLR 2027. Code: https://github.com/x" and "suggestion" not in h
    e = session.get(BibEntry, "2602.00001")
    assert e.status == "unchecked" and e.venue is None and e.title.endswith("(camera-ready)")
    assert b.hints(session, ["2602.99999"]) == [{"paper_id": "2602.99999", "found": False}]


# ---------------------------------------------------------------------------
# fix_bibtex (sync, no lookups)
# ---------------------------------------------------------------------------
BIB = """% my refs
@article{kirillov2023segment,
  title={Segment {A}nything},
  author={Kirillov, Alexander and others},
  journal={arXiv preprint arXiv:2304.02643},
  year={2023}
}

@inproceedings{he2016deep, title={Deep residual learning}, author={He, Kaiming}, booktitle={CVPR}, year={2016}}
@misc{liu2023visual,
      title={Visual Instruction Tuning},
      author={Haotian Liu and Chunyuan Li},
      year={2023}, eprint={2304.08485}, archivePrefix={arXiv}, primaryClass={cs.CV}
}
@article{DBLP:journals/corr/abs-2601-00009,
  author = {A. Nobody}, title = "Still a Preprint",
  journal = {CoRR}, volume = {abs/2601.00009}, year = {2026}
}
@article{noid, title={No Id Here}, author={X}, journal={arXiv preprint}, year={2025}}
@string{foo = "bar"}
"""


def test_parse_bibtex():
    entries = b.parse_bibtex(BIB)
    assert [e.key for e in entries] == ["kirillov2023segment", "he2016deep", "liu2023visual",
                                        "DBLP:journals/corr/abs-2601-00009", "noid"]
    assert entries[0].fields["title"] == "Segment {A}nything"
    assert entries[3].fields["title"] == "Still a Preprint"
    assert [b.arxiv_id_of(e) for e in entries] == ["2304.02643", None, "2304.08485", "2601.00009", None]
    assert [b.is_preprint(e) for e in entries] == [True, False, True, True, True]


def test_fix_bibtex_syncs_and_lists_open_items(session, monkeypatch):
    ax = Arxiv(monkeypatch)
    for pid in ("2304.02643", "2304.08485", "2601.00009"):
        ax.meta[pid] = _meta(pid)

    first = b.fix_bibtex(session, BIB)
    assert first["bibtex"] == BIB and first["changes"] == []
    assert [o["cite_key"] for o in first["needs_check"]] == ["kirillov2023segment", "liu2023visual",
                                                             "DBLP:journals/corr/abs-2601-00009"]
    assert first["no_arxiv_id"] == [{"cite_key": "noid", "title": "No Id Here"}]

    # The agent checks and writes back
    b.set_status(session, "2304.02643", "published", "ICCV", "conference", 2023)
    b.set_status(session, "2304.08485", "published", "NeurIPS", "conference", 2023)
    b.set_status(session, "2601.00009", "preprint")

    ax.calls.clear()
    res = b.fix_bibtex(session, BIB)
    out = res["bibtex"]
    assert ax.calls == []   # everything already in the library
    assert out.startswith("% my refs\n@inproceedings{kirillov2023segment,\n  title     = {Segment {A}nything},\n"
                          "  author    = {Kirillov, Alexander and others},\n  booktitle = {ICCV},\n  year      = {2023}\n}")
    assert "@inproceedings{he2016deep, title={Deep residual learning}" in out           # untouched
    assert "@inproceedings{liu2023visual,\n  title     = {Visual Instruction Tuning},\n" in out
    assert "journal = {CoRR}, volume = {abs/2601.00009}" in out                          # confirmed preprint
    assert out.rstrip().endswith('@string{foo = "bar"}')
    assert [c["cite_key"] for c in res["changes"]] == ["kirillov2023segment", "liu2023visual"]
    assert res["needs_check"] == []


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------
def test_api_roundtrip(client, monkeypatch):
    ax = Arxiv(monkeypatch)
    ax.meta["2602.00001"] = _meta("2602.00001", comment="Accepted to CVPR 2026")
    d = client.get("/api/bibtex", params={"ids": "2602.00001,arXiv:2602.00404"}).json()
    assert d["missing"] == ["2602.00404"] and d["needs_check"] == ["2602.00001"]
    assert d["bibtex"].startswith("@article{yuan2026great,")

    h = client.get("/api/bibtex/hints", params={"ids": "2602.00001"}).json()["hints"][0]
    assert h["comment"] == "Accepted to CVPR 2026"

    r = client.put("/api/bibtex/2602.00001/status",
                   json={"venue": "CVPR", "venue_type": "conference", "year": 2026, "evidence": "arXiv comment"})
    assert r.status_code == 200 and r.json()["venue_type"] == "conference" and not r.json()["needs_check"]
    assert client.put("/api/bibtex/2602.00001/status", json={"venue": "CVPR", "year": 2026}).status_code == 422

    d = client.get("/api/bibtex").json()
    assert d["needs_check"] == [] and d["bibtex"].startswith("@inproceedings{yuan2026great,")
    assert client.get("/api/bibtex/2602.00001/entry").json()["venue"] == "CVPR"

    ax.down = True
    assert client.get("/api/bibtex/hints", params={"ids": "2602.00001"}).status_code == 502
    assert client.delete("/api/bibtex/2602.00001/entry").status_code == 200
    assert client.get("/api/bibtex").json()["entries"] == []

import React, { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ChevronLeft, ExternalLink, Quote, Check, BookOpen, FileText, RefreshCw } from 'lucide-react';
import { format } from 'date-fns';
import ReactMarkdown from 'react-markdown';
import TopBar from '../components/TopBar';
import ScoreEditor from '../components/ScoreEditor';
import ScoreBreakdown from '../components/ScoreBreakdown';
import AuthorList from '../components/AuthorList';
import RelatedPapers from '../components/RelatedPapers';
import { companyLogo } from '../lib/companyLogo';
import { VERDICT_LABEL, finalVerdict } from '../lib/papers';
import { copyText } from '../lib/clipboard';

const API_URL = '/api'; // All backend endpoints live under /api (same origin)
const BUSY = ['STARTING', 'PENDING', 'RUNNING'];

// Only the "## TL;DR" section is shown; older papers may still carry the long structured summary in the DB.
function tldrOnly(md) {
    const text = (md || '').replace(/^```[a-zA-Z]*\n?/i, '').replace(/\n?```$/i, '').trim();
    const lines = text.split('\n');
    const start = lines.findIndex(l => /^##\s*TL;?DR/i.test(l));
    if (start < 0) return text;
    const rest = lines.slice(start + 1);
    const end = rest.findIndex(l => /^##\s/.test(l));
    return (end < 0 ? rest : rest.slice(0, end)).join('\n').trim();
}

// all_categories is stored as a Python-style list string
function parseCategories(paper) {
    try {
        return JSON.parse((paper.all_categories || '[]').replace(/'/g, '"'));
    } catch {
        return [paper.category_primary];
    }
}

// The publication date as stored (UTC day), e.g. "November 24, 2026"
function longDate(iso) {
    if (!iso) return '';
    const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
    return format(new Date(y, m - 1, d), 'MMMM d, yyyy');
}

const PaperDetail = () => {
    const { id } = useParams();
    const navigate = useNavigate();
    const [paper, setPaper] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [bibState, setBibState] = useState('idle'); // idle | loading | copied | error
    const [bibJournal, setBibJournal] = useState(null);
    const [bibText, setBibText] = useState(null);   // shown for manual copying when the browser refuses
    const [deepState, setDeepState] = useState('NONE'); // NONE | PENDING | RUNNING | DONE | ERROR | STARTING
    const pollRef = useRef(null);

    const fetchPaper = async () => {
        const res = await axios.get(`${API_URL}/papers/${id}`);
        setPaper(res.data);
    };

    // Deep read (verdict pipeline): bilingual reading page at /read/:id
    const pollDeepRead = () => {
        clearInterval(pollRef.current);
        let attempts = 0;
        pollRef.current = setInterval(async () => {
            attempts++;
            try {
                const res = await axios.get(`${API_URL}/papers/${id}/reading`);
                setDeepState(res.data.status);
                if (res.data.status === 'DONE' || res.data.status === 'ERROR' || attempts >= 60) {
                    clearInterval(pollRef.current);
                    if (res.data.status === 'DONE') await fetchPaper();
                }
            } catch {
                clearInterval(pollRef.current);
            }
        }, 5000);
    };

    const handleDeepRead = async () => {
        if (deepState === 'DONE') {
            window.open(`/read/${id}`, '_blank');
            return;
        }
        if (BUSY.includes(deepState)) return;
        setDeepState('STARTING');
        try {
            const res = await axios.post(`${API_URL}/papers/${id}/deep-read`);
            setDeepState(res.data.status === 'STARTED' ? 'PENDING' : res.data.status);
            if (res.data.status !== 'DONE') pollDeepRead();
        } catch (err) {
            console.error(err);
            alert(err.response?.data?.detail || 'Failed to start the deep read');
            setDeepState('ERROR');
        }
    };

    useEffect(() => {
        if (!id) return;
        setDeepState('NONE');
        axios.get(`${API_URL}/papers/${id}/reading`).then(res => {
            setDeepState(res.data.status);
            if (res.data.status === 'PENDING' || res.data.status === 'RUNNING') pollDeepRead();
        }).catch(() => {});
        return () => clearInterval(pollRef.current);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id]);

    // Adds the paper to the BibTeX library (venue auto-detected) and copies the entry
    const handleCopyBibtex = async () => {
        if (bibState === 'loading') return;
        setBibState('loading');
        try {
            const res = await axios.get(`${API_URL}/bibtex/${id}/entry`);
            setBibJournal(res.data.status === 'published' ? `${res.data.venue} ${res.data.year}` : null);
            if (await copyText(res.data.bibtex)) {
                setBibText(null);
                setBibState('copied');
                setTimeout(() => setBibState('idle'), 2500);
            } else {
                setBibText(res.data.bibtex);
                setBibState('idle');
            }
        } catch (err) {
            console.error(err);
            setBibState('error');
            setTimeout(() => setBibState('idle'), 2500);
        }
    };

    useEffect(() => {
        if (!id) return;
        setLoading(true);
        setError(null);
        fetchPaper()
            .catch(err => {
                setError(err.response?.status === 404 ? 'notfound' : 'Failed to load paper details.');
                console.error(err);
            })
            .finally(() => setLoading(false));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id]);

    // Set document title to arxiv ID
    useEffect(() => {
        if (id) document.title = `${id} - Paper Agent`;
        return () => { document.title = 'Paper Agent'; };
    }, [id]);

    const goBack = () => {
        if (window.history.length > 1) navigate(-1);
        else window.close();
    };

    const bibButton = (
        <button type="button" onClick={handleCopyBibtex} disabled={bibState === 'loading'} className="pa-btn"
            title="Copy BibTeX (with the venue once it has been confirmed as published)">
            {bibState === 'copied' ? <Check size={14} /> : <Quote size={14} />}
            {bibState === 'loading' ? 'Loading…'
                : bibState === 'copied' ? `Copied${bibJournal ? ` (${bibJournal})` : ''}`
                : bibState === 'error' ? 'BibTeX failed'
                : 'BibTeX'}
        </button>
    );
    const bibPanel = bibText && (
        <div className="pa-bibtex">
            <div className="pa-bibtex-head">
                <span>Your browser blocked automatic copying here. Select the entry and copy it.</span>
                <button type="button" className="pa-btn" onClick={() => setBibText(null)}>Close</button>
            </div>
            <textarea readOnly value={bibText} rows={Math.min(14, bibText.split('\n').length + 1)}
                onFocus={e => e.target.select()} autoFocus />
        </div>
    );

    let body;
    if (loading) {
        body = <div className="pa-sentinel"><RefreshCw className="animate-spin" size={22} /></div>;
    } else if (error === 'notfound') {
        // e.g. an arXiv id that is only in the BibTeX library
        body = (
            <div className="pa-empty">
                <h3>{id} is not in the library</h3>
                <p>The agent has not fetched this paper. You can still open it on arXiv or copy its BibTeX.</p>
                <div className="pa-controls pa-actions" style={{ justifyContent: 'center' }}>
                    <a className="pa-btn" href={`https://arxiv.org/abs/${id}`} target="_blank" rel="noopener noreferrer">
                        <ExternalLink size={14} /> arXiv
                    </a>
                    {bibButton}
                    <button type="button" className="pa-btn" onClick={goBack}>Go back</button>
                </div>
                {bibPanel}
            </div>
        );
    } else if (error || !paper) {
        body = (
            <div className="pa-empty">
                <h3>{error || 'Paper not found'}</h3>
                <p><button type="button" className="pa-btn" onClick={goBack}>Go Back</button></p>
            </div>
        );
    } else {
        const cats = parseCategories(paper);
        const verdict = finalVerdict(paper.score_reason);
        const logo = companyLogo(paper.main_company);
        const busy = BUSY.includes(deepState);
        body = (
            <>
                <article className="pa-hero pa-paper">
                    <div className="pa-card-head">
                        {verdict && <span className={`pill ${verdict}`}>{VERDICT_LABEL[verdict] || verdict}</span>}
                        <ScoreEditor key={paper.id} paper={paper} onSaved={() => fetchPaper().catch(() => {})} />
                        <span className="pa-meta">{paper.id} · {longDate(paper.published_at)}</span>
                        {logo && <img className="pa-logo" src={logo} alt={paper.main_company} title={paper.main_company} />}
                    </div>
                    <h1>{paper.title}</h1>
                    <div className="pa-authors">
                        <AuthorList authors={paper.authors} linkClassName="au" />
                    </div>
                    {paper.main_affiliation && <div className="pa-meta pa-aff">{paper.main_affiliation}</div>}
                    {cats.length > 0 && (
                        <div className="pa-foot">
                            {cats.map(c => <span key={c} className="chip">{c}</span>)}
                        </div>
                    )}
                    <div className="pa-controls pa-actions">
                        <button type="button" onClick={handleDeepRead} disabled={busy} className="pa-btn primary"
                            title={deepState === 'DONE' ? 'Open the bilingual reading page' : 'Deep read with Claude: verdict, summary, paragraph-by-paragraph Chinese notes and translation (~1-2 min)'}>
                            {busy ? <RefreshCw size={14} className="animate-spin" /> : <BookOpen size={14} />}
                            {deepState === 'DONE' ? 'Read'
                                : busy ? 'Deep reading…'
                                : deepState === 'ERROR' ? 'Deep read failed — retry'
                                : 'Deep read'}
                        </button>
                        {paper.pdf_url && (
                            <a className="pa-btn" href={paper.pdf_url} target="_blank" rel="noopener noreferrer">
                                <FileText size={14} /> PDF
                            </a>
                        )}
                        <a className="pa-btn" href={`https://arxiv.org/abs/${paper.id}`} target="_blank" rel="noopener noreferrer">
                            <ExternalLink size={14} /> arXiv
                        </a>
                        {bibButton}
                    </div>
                    {bibPanel}
                </article>

                <section className="pa-section">
                    <h2>TL;DR</h2>
                    {paper.summary_personalized ? (
                        <div className="pa-md">
                            <ReactMarkdown>{tldrOnly(paper.summary_personalized)}</ReactMarkdown>
                        </div>
                    ) : (
                        <p className="pa-meta">No personalized summary available.</p>
                    )}
                </section>

                {paper.score_reason && (
                    <section className="pa-section">
                        <h2>Scoring</h2>
                        <ScoreBreakdown scoreReason={paper.score_reason} userScore={paper.user_score} />
                    </section>
                )}

                <section className="pa-section">
                    <h2>Abstract</h2>
                    <p className="pa-abstract">{paper.summary_generic}</p>
                </section>

                <RelatedPapers paperId={paper.id} />
            </>
        );
    }

    return (
        <div className="pa">
            <TopBar />
            <main className="pa-main pa-doc">
                <button type="button" className="pa-back" onClick={goBack}><ChevronLeft size={14} />Back</button>
                {body}
            </main>
        </div>
    );
};

export default PaperDetail;

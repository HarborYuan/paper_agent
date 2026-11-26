import React, { useState } from 'react';
import axios from 'axios';
import { Check, X } from 'lucide-react';
import AuthorList from './AuthorList';
import { companyLogo } from '../lib/companyLogo';

const API_URL = '/api';
const VERDICT_LABEL = { must_read: 'Must Read', worth_reading: 'Worth Reading', skim: 'Skim', skip: 'Skip' };

const shortDate = (iso) => {
    if (!iso) return '';
    const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

// One paper on the home page, styled like the cards of the Picks page. Takes the light
// card record from /api/papers/feed (or the `view=card` search endpoints).
const DigestCard = ({ paper, similarity }) => {
    const [score, setScore] = useState(paper.user_score ?? paper.score);
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(score ?? 0);

    const saveScore = async (e) => {
        e.stopPropagation();
        const val = parseInt(draft, 10);
        if (isNaN(val) || val < 0 || val > 100) { alert('Score must be 0-100'); return; }
        try {
            await axios.patch(`${API_URL}/papers/${paper.id}/score`, null, { params: { score: val } });
            setScore(val);
            setEditing(false);
        } catch (err) {
            console.error('Failed to update score', err);
            alert('Failed to update score');
        }
    };

    const open = (e) => {
        if (e.target.closest('a,button,input')) return;
        window.open(`/paper/${paper.id}`, '_blank');
    };

    const cats = paper.all_categories || [];
    const logo = companyLogo(paper.main_company);
    const rd = paper.reading || {};
    const fl = rd.flags || {};
    const scoreTitle = paper.user_score != null
        ? 'User score · click to edit'
        : `${paper.score_stage1 != null ? `Screen ${paper.score_stage1 / 20}/5 → ` : ''}final ${paper.score ?? '–'}${paper.score_model ? ` (${paper.score_model})` : ''} · click to edit`;

    return (
        <article className="pa-card" onClick={open}>
            <div className="pa-card-head">
                {paper.verdict && <span className={`pill ${paper.verdict}`}>{VERDICT_LABEL[paper.verdict] || paper.verdict}</span>}
                {editing ? (
                    <span className="pa-score-edit" onClick={e => e.stopPropagation()}>
                        <input type="number" min="0" max="100" value={draft} autoFocus
                            onChange={e => setDraft(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') saveScore(e); if (e.key === 'Escape') setEditing(false); }} />
                        <button type="button" onClick={saveScore} title="Save"><Check size={13} /></button>
                        <button type="button" onClick={e => { e.stopPropagation(); setEditing(false); }} title="Cancel"><X size={13} /></button>
                    </span>
                ) : (
                    <button type="button" className={`pa-score ${score == null ? '' : score >= 85 ? 'hi' : 'lo'}`} title={scoreTitle}
                        onClick={e => { e.stopPropagation(); setDraft(score ?? 0); setEditing(true); }}>
                        {score == null ? 'Set score' : `★ ${score}`}
                    </button>
                )}
                {similarity != null && <span className="chip p" title="Embedding similarity to your query">{(similarity * 100).toFixed(0)}% match</span>}
                <span className="pa-meta">{paper.id} · {shortDate(paper.published_at)}</span>
            </div>
            <h3><a href={`/paper/${paper.id}`} target="_blank" rel="noreferrer">{paper.title}</a></h3>
            <div className="pa-authors">
                <AuthorList authors={paper.authors} short linkClassName="au" moreClassName="pa-more" />
            </div>
            {paper.main_affiliation && <div className="pa-meta">{paper.main_affiliation}</div>}
            {paper.tldr
                ? <p className="tl">{paper.tldr}</p>
                : paper.abstract && <p className="tl abs">{paper.abstract}</p>}
            <div className="pa-foot">
                {cats.slice(0, 3).map(c => <span key={c} className="chip">{c}</span>)}
                {cats.length > 3 && <span className="chip" title={cats.slice(3).join(', ')}>+{cats.length - 3}</span>}
                {rd.status === 'DONE' && <a className="chip p" href={`/read/${paper.id}`} target="_blank" rel="noreferrer">reading page</a>}
                {fl.q > 0 && <span className="chip q">{fl.q} questionable</span>}
                {fl.b > 0 && <span className="chip b">{fl.b} big claim</span>}
                <span className="pa-links">
                    <a href={`/read/${paper.id}`} target="_blank" rel="noreferrer" title="Bilingual reading page">Read</a>
                    {paper.pdf_url && <a href={paper.pdf_url} target="_blank" rel="noopener noreferrer">PDF</a>}
                    <a href={`https://arxiv.org/abs/${paper.id}`} target="_blank" rel="noopener noreferrer">arXiv</a>
                </span>
                {logo && <img className="pa-logo" src={logo} alt={paper.main_company} title={paper.main_company} />}
            </div>
        </article>
    );
};

export default DigestCard;

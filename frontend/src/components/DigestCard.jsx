import React from 'react';
import AuthorList from './AuthorList';
import ScoreEditor from './ScoreEditor';
import { companyLogo } from '../lib/companyLogo';
import { VERDICT_LABEL } from '../lib/papers';


const shortDate = (iso) => {
    if (!iso) return '';
    const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

// One paper on the home page, styled like the cards of the Picks page. Takes the light
// card record from /api/papers/feed (or the `view=card` search endpoints).
const DigestCard = ({ paper, similarity }) => {
    const open = (e) => {
        if (e.target.closest('a,button,input')) return;
        window.open(`/paper/${paper.id}`, '_blank');
    };

    const cats = paper.all_categories || [];
    const logo = companyLogo(paper.main_company);
    const rd = paper.reading || {};
    const fl = rd.flags || {};

    return (
        <article className="pa-card" onClick={open}>
            <div className="pa-card-head">
                {paper.verdict && <span className={`pill ${paper.verdict}`}>{VERDICT_LABEL[paper.verdict] || paper.verdict}</span>}
                <ScoreEditor paper={paper} />
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

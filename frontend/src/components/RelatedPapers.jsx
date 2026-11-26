import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { Sparkles } from 'lucide-react';

const API_URL = '/api';

// Embedding neighbours of a paper, as a compact list in the `.pa` look (home.css).
export default function RelatedPapers({ paperId, k = 8 }) {
    // `forId` marks which paper the state belongs to; until the new response arrives, nothing is shown.
    const [state, setState] = useState({ forId: null, available: false, results: [] });

    useEffect(() => {
        let cancelled = false;
        axios.get(`${API_URL}/papers/${paperId}/related`, { params: { k } })
            .then(res => { if (!cancelled) setState({ forId: paperId, available: res.data.available, results: res.data.results || [] }); })
            .catch(() => { if (!cancelled) setState({ forId: paperId, available: false, results: [] }); });
        return () => { cancelled = true; };
    }, [paperId, k]);

    if (state.forId !== paperId) return null;
    if (!state.available) {
        return (
            <p className="pa-note">
                <Sparkles size={13} /> No embedding for this paper yet — related papers appear after the next run or an embeddings backfill (Settings).
            </p>
        );
    }
    if (!state.results.length) return null;

    return (
        <section className="pa-section">
            <h2><Sparkles size={17} /> Related papers</h2>
            <ul className="pa-related">
                {state.results.map(r => (
                    <li key={r.id}>
                        <Link to={`/paper/${r.id}`}>
                            <span className="m" title="Embedding similarity">{(r.similarity * 100).toFixed(0)}%</span>
                            <span className="txt">
                                <span className="t">{r.title}</span>
                                <span className="pa-meta">{(r.published_at || '').slice(0, 10)}{r.main_affiliation ? ` · ${r.main_affiliation}` : ''}</span>
                            </span>
                            {r.score != null && <span className={`pa-score ${r.score >= 85 ? 'hi' : 'lo'}`}>★ {r.score}</span>}
                        </Link>
                    </li>
                ))}
            </ul>
        </section>
    );
}

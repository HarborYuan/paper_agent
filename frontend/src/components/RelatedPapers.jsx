import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { Sparkles, Star } from 'lucide-react';

const API_URL = '/api';

export default function RelatedPapers({ paperId, k = 8 }) {
    const [state, setState] = useState({ loading: true, available: false, results: [] });

    useEffect(() => {
        let cancelled = false;
        setState({ loading: true, available: false, results: [] });
        axios.get(`${API_URL}/papers/${paperId}/related`, { params: { k } })
            .then(res => { if (!cancelled) setState({ loading: false, available: res.data.available, results: res.data.results || [] }); })
            .catch(() => { if (!cancelled) setState({ loading: false, available: false, results: [] }); });
        return () => { cancelled = true; };
    }, [paperId, k]);

    if (state.loading) return null;
    if (!state.available) {
        return (
            <div className="mt-10 pt-6 border-t border-slate-700/50 text-xs text-slate-500 flex items-center gap-2">
                <Sparkles size={12} /> No embedding for this paper yet — related papers appear after the next run or an embeddings backfill (Settings).
            </div>
        );
    }
    if (!state.results.length) return null;

    return (
        <div className="mt-10 pt-6 border-t border-slate-700/50">
            <h3 className="text-xl font-bold text-slate-200 mb-4 font-display flex items-center gap-2"><Sparkles size={18} className="text-purple-400" /> Related papers</h3>
            <ul className="space-y-2">
                {state.results.map(r => {
                    const dateStr = r.published_at ? new Date(r.published_at.endsWith('Z') ? r.published_at : `${r.published_at}Z`).toISOString().slice(0, 10) : '';
                    return (
                        <li key={r.id}>
                            <Link to={`/paper/${r.id}`} className="group flex items-center gap-3 p-3 rounded-xl bg-slate-900/40 border border-slate-800 hover:border-cyan-500/40 transition-colors">
                                <div className="w-16 shrink-0">
                                    <div className="text-[10px] uppercase tracking-wider text-slate-500">match</div>
                                    <div className="font-mono text-sm text-purple-300">{(r.similarity * 100).toFixed(0)}%</div>
                                </div>
                                <div className="min-w-0 flex-1">
                                    <div className="text-sm font-semibold text-slate-200 group-hover:text-cyan-300 truncate">{r.title}</div>
                                    <div className="text-[11px] text-slate-500 truncate">{dateStr}{r.main_affiliation ? ` · ${r.main_affiliation}` : ''}</div>
                                </div>
                                {r.score !== null && r.score !== undefined && (
                                    <span className={`shrink-0 flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold ${r.score >= 85 ? 'bg-green-500/20 text-green-400' : 'bg-slate-700 text-slate-300'}`}><Star size={11} fill="currentColor" />{r.score}</span>
                                )}
                            </Link>
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}

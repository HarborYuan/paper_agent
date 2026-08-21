import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { ChevronRight, Newspaper, RefreshCw, Send, Trash2, Calendar, FileText, Check, Sparkles } from 'lucide-react';

const API_URL = '/api'; // All backend endpoints live under /api (same origin)

const KIND_META = {
    daily: { label: 'Daily', color: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30' },
    weekly: { label: 'Weekly', color: 'bg-purple-500/15 text-purple-300 border-purple-500/30' },
    monthly: { label: 'Monthly', color: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
};

const mdComponents = {
    h2: ({ children }) => <h2 className="text-lg font-bold text-cyan-400 mt-6 mb-2 first:mt-0">{children}</h2>,
    h3: ({ children }) => <h3 className="text-base font-bold text-slate-200 mt-4 mb-2">{children}</h3>,
    p: ({ children }) => <p className="leading-relaxed text-slate-300 mb-3">{children}</p>,
    ul: ({ children }) => <ul className="list-disc list-outside pl-5 space-y-1 text-slate-300 mb-3">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal list-outside pl-5 space-y-1 text-slate-300 mb-3">{children}</ol>,
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    strong: ({ children }) => <strong className="text-slate-100 font-semibold">{children}</strong>,
    code: ({ children }) => <code className="bg-slate-800 px-1.5 py-0.5 rounded text-cyan-300 text-sm break-words">{children}</code>,
    a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-cyan-400 hover:underline">{children}</a>,
};

// Turn "[2608.18532]" citations into links to the paper page
function linkifyIds(md) {
    return md.replace(/\[(\d{4}\.\d{4,5})(v\d+)?\]/g, (m, id) => `[${id}](/paper/${id})`);
}

export default function Reports() {
    const [reports, setReports] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState(null);
    const [kindFilter, setKindFilter] = useState('');
    const [genKind, setGenKind] = useState('weekly');
    const [genDate, setGenDate] = useState(() => new Date().toISOString().slice(0, 10));
    const [generating, setGenerating] = useState(false);
    const [pushing, setPushing] = useState(false);
    const [msg, setMsg] = useState(null);

    const load = useCallback(async (keepSelection = true) => {
        setLoading(true);
        try {
            const res = await axios.get(`${API_URL}/reports`, { params: { limit: 60, ...(kindFilter ? { kind: kindFilter } : {}) } });
            setReports(res.data);
            if (!keepSelection || !selected) {
                setSelected(res.data[0] || null);
            } else {
                const still = res.data.find(r => r.id === selected.id);
                setSelected(still || res.data[0] || null);
            }
        } catch (e) {
            console.error('Failed to load reports', e);
        } finally {
            setLoading(false);
        }
    }, [kindFilter]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => { load(false); }, [load]);

    const handleGenerate = async () => {
        setGenerating(true); setMsg(null);
        try {
            const res = await axios.post(`${API_URL}/reports/generate`, { kind: genKind, date: genDate });
            setMsg({ type: 'ok', text: `Generated ${res.data.title}` });
            await load();
            setSelected(res.data);
        } catch (e) {
            setMsg({ type: 'err', text: e.response?.data?.detail || 'Generation failed' });
        } finally {
            setGenerating(false);
        }
    };

    const handlePush = async () => {
        if (!selected) return;
        setPushing(true); setMsg(null);
        try {
            const res = await axios.post(`${API_URL}/reports/${selected.id}/push`);
            setSelected(res.data);
            setReports(rs => rs.map(r => r.id === res.data.id ? res.data : r));
            setMsg({ type: 'ok', text: 'Pushed to Lark.' });
        } catch (e) {
            setMsg({ type: 'err', text: e.response?.data?.detail || 'Push failed' });
        } finally {
            setPushing(false);
        }
    };

    const handleDelete = async () => {
        if (!selected || !window.confirm(`Delete "${selected.title}"?`)) return;
        try {
            await axios.delete(`${API_URL}/reports/${selected.id}`);
            setSelected(null);
            await load(false);
        } catch (e) {
            setMsg({ type: 'err', text: e.response?.data?.detail || 'Delete failed' });
        }
    };

    const stats = selected?.stats ? (() => { try { return JSON.parse(selected.stats); } catch { return null; } })() : null;

    return (
        <div className="min-h-screen bg-[#0f172a] text-slate-200 p-6 md:p-12 font-sans">
            <header className="max-w-6xl mx-auto mb-10">
                <Link to="/" className="text-cyan-400 hover:text-cyan-300 mb-6 inline-block font-medium flex items-center gap-2">
                    <ChevronRight size={16} className="rotate-180" />
                    Back to Digest
                </Link>
                <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
                    <div>
                        <h1 className="text-4xl md:text-5xl font-black text-white mb-2 flex items-center gap-3">
                            <Newspaper className="text-cyan-400" size={40} />
                            <span>Trend <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-500">Reports</span></span>
                        </h1>
                        <p className="text-slate-400 font-medium">Daily, weekly and monthly LLM-written summaries of what made it through — topics, institutions, must-reads.</p>
                    </div>
                    {/* Generate */}
                    <div className="flex flex-wrap items-center gap-2 bg-slate-800/60 border border-slate-700 rounded-xl p-2">
                        <select value={genKind} onChange={e => setGenKind(e.target.value)} className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500">
                            <option value="daily">Daily</option>
                            <option value="weekly">Weekly</option>
                            <option value="monthly">Monthly</option>
                        </select>
                        <input type="date" value={genDate} onChange={e => setGenDate(e.target.value)} className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500" title={genKind === 'weekly' ? 'The 7 days before this date' : genKind === 'monthly' ? 'Previous month if the 1st, else the month containing this date' : 'This day'} />
                        <button onClick={handleGenerate} disabled={generating} className={`flex items-center gap-2 px-4 py-2 rounded-lg font-bold transition-colors ${generating ? 'bg-slate-700 text-slate-500 cursor-wait' : 'bg-cyan-500 hover:bg-cyan-400 text-slate-900'}`}>
                            <Sparkles size={16} className={generating ? 'animate-pulse' : ''} /> {generating ? 'Generating…' : 'Generate'}
                        </button>
                    </div>
                </div>
                {msg && <p className={`mt-3 text-sm ${msg.type === 'ok' ? 'text-green-400' : 'text-red-400'}`}>{msg.text}</p>}
            </header>

            <main className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
                {/* List */}
                <aside>
                    <div className="flex items-center gap-1 mb-3">
                        {['', 'daily', 'weekly', 'monthly'].map(k => (
                            <button key={k} onClick={() => setKindFilter(k)} className={`px-3 py-1 rounded-lg text-xs font-bold transition-colors ${kindFilter === k ? 'bg-cyan-500 text-slate-900' : 'bg-slate-800 text-slate-400 hover:text-white'}`}>{k ? KIND_META[k].label : 'All'}</button>
                        ))}
                        <button onClick={() => load()} className="ml-auto p-1.5 rounded-lg bg-slate-800 text-slate-400 hover:text-white" title="Reload"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /></button>
                    </div>
                    {reports.length === 0 && !loading && (
                        <p className="text-sm text-slate-500 bg-slate-800/40 border border-slate-700/60 rounded-xl p-4">No reports yet. Reports are generated automatically after each daily run (daily) and on the configured weekday / 1st of the month (weekly / monthly) — or generate one now.</p>
                    )}
                    <ul className="space-y-2">
                        {reports.map(r => (
                            <li key={r.id}>
                                <button onClick={() => setSelected(r)} className={`w-full text-left p-3 rounded-xl border transition-colors ${selected?.id === r.id ? 'bg-slate-800 border-cyan-500/50' : 'bg-slate-800/40 border-slate-700/60 hover:border-slate-500'}`}>
                                    <div className="flex items-center justify-between gap-2 mb-1">
                                        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${KIND_META[r.kind]?.color || ''}`}>{r.kind}</span>
                                        <span className="text-[11px] text-slate-500 flex items-center gap-1">{r.pushed && <Check size={11} className="text-green-400" title="Pushed to Lark" />}{r.paper_count} papers</span>
                                    </div>
                                    <div className="text-sm font-semibold text-slate-200 truncate">{r.period_label}</div>
                                    <div className="text-[11px] text-slate-500 flex items-center gap-1 mt-0.5"><Calendar size={10} /> {new Date(r.created_at + (r.created_at.endsWith('Z') ? '' : 'Z')).toLocaleString()}</div>
                                </button>
                            </li>
                        ))}
                    </ul>
                </aside>

                {/* Detail */}
                <section>
                    {selected ? (
                        <article className="bg-slate-800/50 backdrop-blur-md border border-slate-700/50 rounded-2xl p-6 md:p-8 shadow-2xl">
                            <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
                                <div>
                                    <h2 className="text-2xl font-black text-white">{selected.title}</h2>
                                    <p className="text-xs text-slate-500 mt-1 font-mono">{selected.model} · {selected.paper_count} papers · {selected.pushed ? `pushed ${new Date(selected.pushed_at + (selected.pushed_at.endsWith('Z') ? '' : 'Z')).toLocaleString()}` : 'not pushed'}</p>
                                </div>
                                <div className="flex items-center gap-2">
                                    <button onClick={handlePush} disabled={pushing} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-bold bg-slate-700/60 text-cyan-300 hover:bg-slate-600 border border-slate-600/50 disabled:opacity-50" title="Send to Lark"><Send size={14} /> {pushing ? 'Pushing…' : (selected.pushed ? 'Push again' : 'Push to Lark')}</button>
                                    <button onClick={handleDelete} className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-slate-700/50" title="Delete"><Trash2 size={16} /></button>
                                </div>
                            </div>
                            {stats && (
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
                                    <Stat label="selected" value={stats.selected} sub={stats.prev ? `prev ${stats.prev.selected}` : null} />
                                    <Stat label="fetched" value={stats.fetched} sub={stats.prev ? `prev ${stats.prev.fetched}` : null} />
                                    <Stat label="stage-2 reviewed" value={stats.stage2_reviewed} />
                                    <Stat label="avg score" value={stats.avg_score ?? '—'} sub={stats.llm_cost_usd !== null && stats.llm_cost_usd !== undefined ? `LLM $${Number(stats.llm_cost_usd).toFixed(3)}` : null} />
                                </div>
                            )}
                            <div className="prose prose-invert prose-slate max-w-none bg-slate-900/30 p-6 rounded-xl border border-slate-700/50">
                                <ReactMarkdown components={mdComponents}>{linkifyIds(selected.content)}</ReactMarkdown>
                            </div>
                            {stats && (stats.companies?.length || stats.universities?.length) ? (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
                                    <TopList title="Companies" rows={stats.companies} />
                                    <TopList title="Universities" rows={stats.universities} />
                                </div>
                            ) : null}
                        </article>
                    ) : (
                        <div className="h-64 flex items-center justify-center text-slate-500 bg-slate-800/30 border border-slate-700/50 rounded-2xl"><FileText size={18} className="mr-2" /> Select a report</div>
                    )}
                </section>
            </main>
        </div>
    );
}

function Stat({ label, value, sub }) {
    return (
        <div className="bg-slate-900/60 border border-slate-700/60 rounded-xl p-3">
            <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{label}</div>
            <div className="text-xl font-bold font-mono text-slate-100">{value ?? '—'}</div>
            {sub && <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>}
        </div>
    );
}

function TopList({ title, rows }) {
    if (!rows || !rows.length) return null;
    return (
        <div className="bg-slate-900/40 border border-slate-700/60 rounded-xl p-4">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">{title}</h4>
            <ul className="space-y-1 text-sm">
                {rows.map(r => (
                    <li key={r.name} className="flex items-center justify-between gap-2">
                        <span className="text-slate-300 truncate">{r.name}</span>
                        <span className="font-mono text-xs text-slate-400 shrink-0">{r.count}{r.prev !== undefined ? <span className={r.count > r.prev ? 'text-green-400' : r.count < r.prev ? 'text-orange-400' : 'text-slate-600'}> ({r.count > r.prev ? '+' : ''}{r.count - r.prev})</span> : null}</span>
                    </li>
                ))}
            </ul>
        </div>
    );
}

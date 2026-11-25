import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { ChevronRight, FolderKanban, Plus, Trash2, Save, Sparkles, X, BookOpen, Pause, Play } from 'lucide-react';

const API_URL = '/api';

const SOURCE_CLS = {
    seed: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
    manual: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
    auto: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30',
};

const splitIds = (txt) => txt.split(/[\s,]+/).map(s => s.trim()
    .replace(/^https?:\/\/arxiv\.org\/(abs|pdf|html)\//, '').replace(/v\d+$/, '')).filter(Boolean);

export default function Projects() {
    const [projects, setProjects] = useState([]);
    const [selected, setSelected] = useState(null);   // full project with papers
    const [draft, setDraft] = useState(null);          // edit / create form
    const [addIds, setAddIds] = useState('');
    const [suggest, setSuggest] = useState(null);
    const [msg, setMsg] = useState(null);

    const loadList = useCallback(async () => {
        const res = await axios.get(`${API_URL}/projects`);
        setProjects(res.data);
        return res.data;
    }, []);

    const open = useCallback(async (id) => {
        const res = await axios.get(`${API_URL}/projects/${id}`);
        setSelected(res.data);
        setDraft({ name: res.data.name, description: res.data.description, keywords: res.data.keywords.join(', ') });
        setSuggest(null);
    }, []);

    useEffect(() => {
        loadList().then(list => { if (list.length) open(list[0].id); }).catch(() => {});
    }, [loadList, open]);

    const flash = (type, text) => { setMsg({ type, text }); setTimeout(() => setMsg(null), 4000); };
    const err = (e) => flash('err', e.response?.data?.detail || 'Request failed');

    const startNew = () => { setSelected(null); setSuggest(null); setDraft({ name: '', description: '', keywords: '', seeds: '' }); };

    const save = async () => {
        const keywords = draft.keywords.split(',').map(s => s.trim()).filter(Boolean);
        try {
            if (selected) {
                await axios.patch(`${API_URL}/projects/${selected.id}`, { name: draft.name, description: draft.description, keywords });
                await open(selected.id);
                flash('ok', 'Saved.');
            } else {
                const res = await axios.post(`${API_URL}/projects`, {
                    name: draft.name, description: draft.description, keywords, seed_paper_ids: splitIds(draft.seeds || ''),
                });
                await open(res.data.id);
                flash('ok', 'Project created.');
            }
            await loadList();
        } catch (e) { err(e); }
    };

    const toggleActive = async () => {
        try {
            await axios.patch(`${API_URL}/projects/${selected.id}`, { active: !selected.active });
            await open(selected.id); await loadList();
        } catch (e) { err(e); }
    };

    const remove = async () => {
        if (!window.confirm(`Delete project "${selected.name}"? Its paper list is removed; the papers stay in the library.`)) return;
        try {
            await axios.delete(`${API_URL}/projects/${selected.id}`);
            setSelected(null); setDraft(null);
            const list = await loadList();
            if (list.length) open(list[0].id);
        } catch (e) { err(e); }
    };

    const addPapers = async (ids, source = 'manual') => {
        try {
            const res = await axios.post(`${API_URL}/projects/${selected.id}/papers`, { paper_ids: ids, source });
            const { added, already, unknown } = res.data;
            flash(unknown.length ? 'err' : 'ok', `Added ${added.length}${already.length ? `, ${already.length} already in` : ''}${unknown.length ? `; not in library: ${unknown.join(', ')} (add them on the home page first)` : ''}`);
            setAddIds('');
            await open(selected.id); await loadList();
        } catch (e) { err(e); }
    };

    const dropPaper = async (pid) => {
        try {
            await axios.delete(`${API_URL}/projects/${selected.id}/papers/${pid}`);
            await open(selected.id); await loadList();
        } catch (e) { err(e); }
    };

    const loadSuggestions = async () => {
        try {
            const res = await axios.get(`${API_URL}/projects/${selected.id}/suggestions`, { params: { k: 20 } });
            setSuggest(res.data);
        } catch (e) { err(e); }
    };

    const input = 'w-full bg-slate-900/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500';

    return (
        <div className="min-h-screen bg-[#0f172a] text-slate-200 p-6 md:p-12 font-sans">
            <header className="max-w-6xl mx-auto mb-8">
                <Link to="/" className="text-cyan-400 hover:text-cyan-300 mb-6 inline-flex font-medium items-center gap-2">
                    <ChevronRight size={16} className="rotate-180" /> Back to Digest
                </Link>
                <div className="flex items-center justify-between gap-4">
                    <h1 className="text-3xl font-black text-white flex items-center gap-3"><FolderKanban className="text-cyan-400" /> Projects</h1>
                    <button onClick={startNew} className="flex items-center gap-2 px-4 py-2 rounded-lg font-bold bg-cyan-600 hover:bg-cyan-500 text-white">
                        <Plus size={16} /> New project
                    </button>
                </div>
                <p className="text-slate-400 text-sm mt-2">New papers are matched to active projects every night (embedding similarity to the seed papers and description, plus the screening model); the reviewer confirms each match.</p>
                {msg && <p className={`mt-3 text-sm ${msg.type === 'ok' ? 'text-green-400' : 'text-red-400'}`}>{msg.text}</p>}
            </header>

            <div className="max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-[240px_1fr] gap-6">
                <nav className="space-y-2">
                    {projects.map(p => (
                        <button key={p.id} onClick={() => open(p.id)}
                            className={`w-full text-left px-4 py-3 rounded-xl border transition ${selected?.id === p.id ? 'bg-slate-800 border-cyan-500/50' : 'bg-slate-800/40 border-slate-700/50 hover:bg-slate-800'}`}>
                            <div className="font-bold text-slate-100 flex items-center justify-between gap-2">
                                <span className="truncate">{p.name}</span>
                                <span className="text-xs text-slate-400 font-mono">{p.n_papers}</span>
                            </div>
                            {!p.active && <div className="text-[11px] text-yellow-400/80">paused</div>}
                        </button>
                    ))}
                    {!projects.length && <p className="text-sm text-slate-500">No projects yet.</p>}
                </nav>

                <main className="space-y-6">
                    {draft && (
                        <section className="bg-slate-800/50 border border-slate-700/50 rounded-2xl p-6 space-y-3">
                            <input className={input + ' text-lg font-bold'} placeholder="Project name" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} />
                            <textarea className={input} rows={4} placeholder="What the project does and what kind of paper it needs — recall uses this text"
                                value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} />
                            <input className={input} placeholder="Keywords, comma separated" value={draft.keywords} onChange={e => setDraft({ ...draft, keywords: e.target.value })} />
                            {!selected && (
                                <input className={input} placeholder="Seed arXiv ids (space or comma separated; must already be in the library)"
                                    value={draft.seeds} onChange={e => setDraft({ ...draft, seeds: e.target.value })} />
                            )}
                            <div className="flex flex-wrap gap-2">
                                <button onClick={save} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-bold bg-cyan-600 hover:bg-cyan-500 text-white"><Save size={14} /> {selected ? 'Save' : 'Create'}</button>
                                {selected && (
                                    <>
                                        <button onClick={toggleActive} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-bold bg-slate-700 hover:bg-slate-600">
                                            {selected.active ? <><Pause size={14} /> Pause recall</> : <><Play size={14} /> Resume recall</>}
                                        </button>
                                        <button onClick={remove} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-bold bg-red-500/20 text-red-300 hover:bg-red-500/30"><Trash2 size={14} /> Delete</button>
                                    </>
                                )}
                            </div>
                        </section>
                    )}

                    {selected && (
                        <section className="bg-slate-800/50 border border-slate-700/50 rounded-2xl p-6">
                            <div className="flex flex-wrap items-center gap-2 mb-4">
                                <input className={input + ' flex-1 min-w-[220px]'} placeholder="Add papers: arXiv ids or URLs" value={addIds} onChange={e => setAddIds(e.target.value)} />
                                <button onClick={() => addPapers(splitIds(addIds))} className="px-3 py-2 rounded-lg text-sm font-bold bg-slate-700 hover:bg-slate-600">Add</button>
                                <button onClick={() => addPapers(splitIds(addIds), 'seed')} className="px-3 py-2 rounded-lg text-sm font-bold bg-purple-500/20 text-purple-300 hover:bg-purple-500/30">Add as seed</button>
                                <button onClick={loadSuggestions} className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-bold bg-cyan-500/15 text-cyan-300 hover:bg-cyan-500/25"><Sparkles size={14} /> Suggestions</button>
                            </div>

                            {suggest && (
                                <div className="mb-6 border border-cyan-500/20 rounded-xl p-4 bg-slate-900/40">
                                    <div className="flex items-center justify-between mb-2">
                                        <h3 className="font-bold text-cyan-300 text-sm">Similar papers already in the library</h3>
                                        <button onClick={() => setSuggest(null)} className="text-slate-500 hover:text-slate-300"><X size={14} /></button>
                                    </div>
                                    <ul className="space-y-1.5">
                                        {suggest.map(p => (
                                            <li key={p.id} className="flex items-center gap-3 text-sm">
                                                <span className="font-mono text-xs text-slate-500 w-12">{p.similarity?.toFixed(3)}</span>
                                                <Link to={`/paper/${p.id}`} className="flex-1 text-slate-200 hover:text-cyan-400 truncate">{p.title}</Link>
                                                <button onClick={() => addPapers([p.id])} className="text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600">Add</button>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            <ul className="divide-y divide-slate-700/50">
                                {selected.papers.map(p => (
                                    <li key={p.id} className="py-3 flex items-start gap-3">
                                        <span className={`shrink-0 mt-0.5 text-[10px] uppercase font-bold px-2 py-0.5 rounded border ${SOURCE_CLS[p.project_source] || SOURCE_CLS.manual}`}>{p.project_source}</span>
                                        <div className="flex-1 min-w-0">
                                            <Link to={`/paper/${p.id}`} className="font-semibold text-slate-100 hover:text-cyan-400">{p.title}</Link>
                                            <div className="text-xs text-slate-500 mt-0.5">
                                                {p.id} · {(p.published_at || '').slice(0, 10)}{p.score != null ? ` · score ${p.score}` : ''}{p.main_affiliation ? ` · ${p.main_affiliation}` : ''}
                                            </div>
                                            {p.project_reason && <div className="text-xs text-cyan-300/80 mt-1">{p.project_reason}</div>}
                                        </div>
                                        <a href={`/read/${p.id}`} target="_blank" rel="noreferrer" title="Reading page" className="text-slate-500 hover:text-cyan-400 mt-1"><BookOpen size={15} /></a>
                                        <button onClick={() => dropPaper(p.id)} title="Remove from project" className="text-slate-600 hover:text-red-400 mt-1"><X size={15} /></button>
                                    </li>
                                ))}
                                {!selected.papers.length && <li className="py-6 text-sm text-slate-500">No papers yet — add seeds or use Suggestions.</li>}
                            </ul>
                        </section>
                    )}
                </main>
            </div>
        </div>
    );
}

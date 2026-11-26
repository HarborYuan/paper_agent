import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { Plus, Trash2, Save, Sparkles, X, BookOpen, Pause, Play } from 'lucide-react';
import TopBar from '../components/TopBar';

const API_URL = '/api';

// chip colours of home.css: seed = purple, auto = accent, manual = plain
const SOURCE_CLS = { seed: 'chip b', manual: 'chip', auto: 'chip p' };

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

    // First load: the list, then the first project
    useEffect(() => {
        let stale = false;
        axios.get(`${API_URL}/projects`)
            .then(res => {
                if (stale) return;
                setProjects(res.data);
                if (res.data.length) open(res.data[0].id);
            })
            .catch(() => {});
        return () => { stale = true; };
    }, [open]);

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

    return (
        <div className="pa">
            <TopBar />

            <main className="pa-main">
                <section className="pa-hero">
                    <div className="pa-kicker">Paper collections for what you are building</div>
                    <div className="pa-author-head">
                        <h1>Projects</h1>
                        <button type="button" onClick={startNew} className="pa-btn primary"><Plus size={14} /> New project</button>
                    </div>
                    <p className="pa-bio">New papers are matched to active projects every night (embedding similarity to the seed papers and description, plus the screening model); the reviewer confirms each match.</p>
                    {msg && <p className={`pa-flash ${msg.type}`}>{msg.text}</p>}
                </section>

                <div className="pa-proj">
                    <nav className="pa-proj-list" aria-label="Projects">
                        {projects.map(p => (
                            <button key={p.id} type="button" onClick={() => open(p.id)} className={selected?.id === p.id ? 'on' : ''}>
                                <span className="nm">{p.name}</span>
                                <span className="n">{p.n_papers}</span>
                                {!p.active && <span className="paused">paused</span>}
                            </button>
                        ))}
                        {!projects.length && <p className="pa-meta">No projects yet.</p>}
                    </nav>

                    <div className="pa-proj-main">
                        {draft && (
                            <section className="pa-section">
                                <h2>{selected ? 'Project' : 'New project'}</h2>
                                <div className="pa-form flat">
                                    <label>
                                        <span>Name</span>
                                        <input className="big" placeholder="Project name" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} />
                                    </label>
                                    <label>
                                        <span>Description</span>
                                        <textarea rows={4} placeholder="What the project does and what kind of paper it needs — recall uses this text"
                                            value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} />
                                    </label>
                                    <label>
                                        <span>Keywords</span>
                                        <input placeholder="Keywords, comma separated" value={draft.keywords} onChange={e => setDraft({ ...draft, keywords: e.target.value })} />
                                    </label>
                                    {!selected && (
                                        <label>
                                            <span>Seed papers</span>
                                            <input placeholder="Seed arXiv ids (space or comma separated; must already be in the library)"
                                                value={draft.seeds} onChange={e => setDraft({ ...draft, seeds: e.target.value })} />
                                        </label>
                                    )}
                                    <div className="pa-row">
                                        <button type="button" onClick={save} className="pa-btn primary"><Save size={14} /> {selected ? 'Save' : 'Create'}</button>
                                        {selected && (
                                            <>
                                                <button type="button" onClick={toggleActive} className="pa-btn">
                                                    {selected.active ? <><Pause size={14} /> Pause recall</> : <><Play size={14} /> Resume recall</>}
                                                </button>
                                                <button type="button" onClick={remove} className="pa-btn danger"><Trash2 size={14} /> Delete</button>
                                            </>
                                        )}
                                    </div>
                                </div>
                            </section>
                        )}

                        {selected && (
                            <section className="pa-section">
                                <h2>Papers <small className="pa-meta">{selected.papers.length}</small></h2>
                                <div className="pa-addrow">
                                    <input className="pa-input" placeholder="Add papers: arXiv ids or URLs" value={addIds} onChange={e => setAddIds(e.target.value)} />
                                    <div className="pa-row">
                                        <button type="button" onClick={() => addPapers(splitIds(addIds))} className="pa-btn">Add</button>
                                        <button type="button" onClick={() => addPapers(splitIds(addIds), 'seed')} className="pa-btn">Add as seed</button>
                                        <button type="button" onClick={loadSuggestions} className="pa-btn"><Sparkles size={14} /> Suggestions</button>
                                    </div>
                                </div>

                                {suggest && (
                                    <div className="pa-suggest">
                                        <div className="hd">
                                            <h3><Sparkles size={14} /> Similar papers already in the library</h3>
                                            <button type="button" onClick={() => setSuggest(null)} title="Close"><X size={15} /></button>
                                        </div>
                                        <ul>
                                            {suggest.map(p => (
                                                <li key={p.id}>
                                                    <span className="m" title="Embedding similarity">{p.similarity?.toFixed(3)}</span>
                                                    <Link to={`/paper/${p.id}`} className="t">{p.title}</Link>
                                                    <button type="button" onClick={() => addPapers([p.id])} className="pa-btn small">Add</button>
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}

                                <ul className="pa-proj-papers">
                                    {selected.papers.map(p => (
                                        <li key={p.id}>
                                            <span className={SOURCE_CLS[p.project_source] || SOURCE_CLS.manual}>{p.project_source}</span>
                                            <div className="txt">
                                                <Link to={`/paper/${p.id}`} className="t">{p.title}</Link>
                                                <div className="pa-meta">
                                                    {p.id} · {(p.published_at || '').slice(0, 10)}{p.score != null ? ` · score ${p.score}` : ''}{p.main_affiliation ? ` · ${p.main_affiliation}` : ''}
                                                </div>
                                                {p.project_reason && <div className="why">{p.project_reason}</div>}
                                            </div>
                                            <a href={`/read/${p.id}`} target="_blank" rel="noreferrer" title="Reading page" className="ic"><BookOpen size={15} /></a>
                                            <button type="button" onClick={() => dropPaper(p.id)} title="Remove from project" className="ic del"><X size={15} /></button>
                                        </li>
                                    ))}
                                    {!selected.papers.length && <li className="pa-meta">No papers yet — add seeds or use Suggestions.</li>}
                                </ul>
                            </section>
                        )}
                    </div>
                </div>
            </main>
        </div>
    );
}

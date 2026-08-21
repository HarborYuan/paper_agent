import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import axios from 'axios';
import { Settings as SettingsIcon, ArrowLeft, Cpu, DollarSign, Activity, Save, RefreshCw, Star, Search, Check, AlertTriangle, Info, FileCog, KeyRound, Clock, Bell, Database, User, Eye, EyeOff } from 'lucide-react';
import { Link } from 'react-router-dom';

const API_URL = '/api'; // All backend endpoints live under /api (same origin)

const TASK_META = {
    score_stage1: { label: 'Stage 1 · Screening', hint: 'Every new paper, title + abstract. Cheap & recall-oriented.' },
    score_stage2: { label: 'Stage 2 · Review', hint: 'Papers above the stage-2 threshold: abstract + start of the PDF, judges relevance and quality. Final score.' },
    summarize: { label: 'Summary', hint: 'Papers above the score threshold: full-text structured summary.' },
    affiliation: { label: 'Affiliation', hint: 'Header parsing for summarized papers (uses the Stage 1 model).' },
    report: { label: 'Reports', hint: 'Daily / weekly / monthly trend reports written from the selected papers + computed stats (≈1.2 calls/day).' },
};

const fmtUSD = (v, digits = 4) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : `$${Number(v).toFixed(digits)}`;
const fmtPrice = (v) => (v === null || v === undefined) ? '—' : `$${Number(v).toFixed(2)}`;
const fmtNum = (v) => (v === null || v === undefined) ? '—' : Number(v).toLocaleString();

/* ------------------------------------------------------------------ */
/* Searchable model picker                                             */
/* ------------------------------------------------------------------ */
function ModelSelect({ label, hint, value, onChange, models, disabled }) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const boxRef = useRef(null);

    useEffect(() => {
        const onDoc = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
        document.addEventListener('mousedown', onDoc);
        return () => document.removeEventListener('mousedown', onDoc);
    }, []);

    const current = models.find(m => m.id === value);
    const filtered = useMemo(() => {
        const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
        const list = terms.length
            ? models.filter(m => terms.every(t => m.id.toLowerCase().includes(t) || (m.name || '').toLowerCase().includes(t)))
            : models;
        return list.slice(0, 80);
    }, [models, query]);

    return (
        <div className="mb-6" ref={boxRef}>
            <div className="flex items-baseline justify-between mb-1">
                <label className="text-sm font-bold text-slate-200">{label}</label>
                {current && (
                    <span className="text-xs text-slate-400 font-mono">
                        in {fmtPrice(current.prompt_price_per_m)} / out {fmtPrice(current.completion_price_per_m)} per 1M · ctx {fmtNum(current.context_length)}
                    </span>
                )}
            </div>
            <p className="text-xs text-slate-500 mb-2">{hint}</p>
            <div className="relative">
                <button
                    type="button"
                    disabled={disabled}
                    onClick={() => setOpen(o => !o)}
                    className={`w-full flex items-center justify-between bg-slate-900 border rounded-lg px-4 py-2.5 text-left font-mono text-sm transition-colors ${open ? 'border-cyan-500' : 'border-slate-700 hover:border-slate-500'} ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                    <span className="flex items-center gap-2 text-slate-200">
                        {current?.recommended && <Star size={12} className="text-yellow-400" fill="currentColor" />}
                        {value || <span className="text-slate-500">select a model…</span>}
                    </span>
                    <span className="text-slate-500 text-xs">{current ? current.name : (models.length ? 'not in catalog' : '')}</span>
                </button>
                {open && (
                    <div className="absolute z-30 mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg shadow-2xl overflow-hidden">
                        <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800">
                            <Search size={14} className="text-slate-500" />
                            <input
                                autoFocus
                                value={query}
                                onChange={e => setQuery(e.target.value)}
                                onKeyDown={e => { if (e.key === 'Escape') setOpen(false); if (e.key === 'Enter' && filtered[0]) { onChange(filtered[0].id); setOpen(false); } }}
                                placeholder="Search models (e.g. sonnet, gpt-5 mini, gemini flash)…"
                                className="flex-1 bg-transparent text-sm text-slate-200 focus:outline-none"
                            />
                            <span className="text-[10px] text-slate-500">{filtered.length}{models.length > filtered.length ? ` / ${models.length}` : ''}</span>
                        </div>
                        <ul className="max-h-72 overflow-y-auto">
                            {filtered.length === 0 && <li className="px-3 py-3 text-sm text-slate-500">No models match.</li>}
                            {filtered.map(m => (
                                <li key={m.id}>
                                    <button
                                        type="button"
                                        onClick={() => { onChange(m.id); setOpen(false); setQuery(''); }}
                                        className={`w-full text-left px-3 py-2 hover:bg-slate-800 flex items-center justify-between gap-3 ${m.id === value ? 'bg-slate-800/70' : ''}`}
                                    >
                                        <span className="min-w-0">
                                            <span className="flex items-center gap-1.5 font-mono text-sm text-slate-200 truncate">
                                                {m.recommended && <Star size={11} className="text-yellow-400 shrink-0" fill="currentColor" />}
                                                {m.id}
                                                {m.id === value && <Check size={12} className="text-cyan-400 shrink-0" />}
                                            </span>
                                            <span className="block text-[11px] text-slate-500 truncate">{m.name}{m.supports_json ? '' : ' · no JSON mode'}</span>
                                        </span>
                                        <span className="shrink-0 text-[11px] font-mono text-slate-400 text-right">
                                            <span className="block">{fmtPrice(m.prompt_price_per_m)} in</span>
                                            <span className="block">{fmtPrice(m.completion_price_per_m)} out</span>
                                        </span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        </div>
    );
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */
export default function Settings() {
    const [loading, setLoading] = useState(true);
    const [settings, setSettings] = useState(null);
    const [models, setModels] = useState([]);
    const [catalogStatus, setCatalogStatus] = useState(null);

    // editable draft
    const [draft, setDraft] = useState({ stage1: '', stage2: '', summary: '', report: '', stage2_threshold: 60, score_threshold: 85 });
    const [saving, setSaving] = useState(false);
    const [saveMsg, setSaveMsg] = useState(null); // {type:'ok'|'err', text}

    const [estimate, setEstimate] = useState(null);
    const [estimating, setEstimating] = useState(false);
    const [usage, setUsage] = useState(null);
    const [usageLoading, setUsageLoading] = useState(true);
    const [saveWarnings, setSaveWarnings] = useState([]);

    // generic configuration (all .env keys)
    const [allSettings, setAllSettings] = useState(null);
    const [cfgDraft, setCfgDraft] = useState({});     // key -> edited value (only touched keys)
    const [cfgSaving, setCfgSaving] = useState(false);
    const [cfgMsg, setCfgMsg] = useState(null);
    const [cfgWarnings, setCfgWarnings] = useState([]);
    const [showSecret, setShowSecret] = useState({});

    // profile
    const [profileDraft, setProfileDraft] = useState('');
    const [profileSaving, setProfileSaving] = useState(false);
    const [profileMsg, setProfileMsg] = useState(null);

    const loadAllSettings = useCallback(async () => {
        try {
            const res = await axios.get(`${API_URL}/settings`);
            setAllSettings(res.data);
            setCfgDraft({});
        } catch (e) {
            console.error('Failed to load configuration', e);
        }
    }, []);

    const loadAll = useCallback(async () => {
        setLoading(true);
        try {
            const [sRes, mRes] = await Promise.all([
                axios.get(`${API_URL}/settings/llm`),
                axios.get(`${API_URL}/models`),
            ]);
            setSettings(sRes.data);
            setDraft({
                stage1: sRes.data.models.stage1,
                stage2: sRes.data.models.stage2,
                summary: sRes.data.models.summary,
                report: sRes.data.models.report,
                stage2_threshold: sRes.data.thresholds.stage2_threshold,
                score_threshold: sRes.data.thresholds.score_threshold,
            });
            setModels(mRes.data.models || []);
            setCatalogStatus(mRes.data.catalog || null);
            setProfileDraft(sRes.data.profile || '');
        } catch (e) {
            console.error('Failed to load settings', e);
            setSaveMsg({ type: 'err', text: 'Failed to load settings. Check backend logs.' });
        } finally {
            setLoading(false);
        }
    }, []);

    const loadUsage = useCallback(async () => {
        setUsageLoading(true);
        try {
            const res = await axios.get(`${API_URL}/llm/usage`, { params: { days: 30 } });
            setUsage(res.data);
        } catch (e) {
            console.error('Failed to load usage', e);
        } finally {
            setUsageLoading(false);
        }
    }, []);

    useEffect(() => { loadAll(); loadUsage(); loadAllSettings(); }, [loadAll, loadUsage, loadAllSettings]);

    // Debounced cost estimate whenever the draft changes
    useEffect(() => {
        if (!draft.stage1 || !draft.stage2 || !draft.summary) return;
        const t = setTimeout(async () => {
            setEstimating(true);
            try {
                const res = await axios.get(`${API_URL}/llm/estimate`, {
                    params: {
                        stage1_model: draft.stage1, stage2_model: draft.stage2, summary_model: draft.summary, report_model: draft.report,
                        stage2_threshold: draft.stage2_threshold, score_threshold: draft.score_threshold,
                    },
                });
                setEstimate(res.data);
            } catch (e) {
                console.error('Estimate failed', e);
            } finally {
                setEstimating(false);
            }
        }, 350);
        return () => clearTimeout(t);
    }, [draft]);

    const dirty = settings && (
        draft.stage1 !== settings.models.stage1 ||
        draft.stage2 !== settings.models.stage2 ||
        draft.summary !== settings.models.summary ||
        draft.report !== settings.models.report ||
        Number(draft.stage2_threshold) !== settings.thresholds.stage2_threshold ||
        Number(draft.score_threshold) !== settings.thresholds.score_threshold
    );

    const handleSave = async () => {
        setSaving(true); setSaveMsg(null);
        try {
            const res = await axios.put(`${API_URL}/settings/llm`, {
                stage1_model: draft.stage1, stage2_model: draft.stage2, summary_model: draft.summary, report_model: draft.report,
                stage2_threshold: Number(draft.stage2_threshold), score_threshold: Number(draft.score_threshold),
            });
            setSettings(res.data);
            setSaveWarnings(res.data.warnings || []);
            setSaveMsg({ type: 'ok', text: `Saved to ${res.data.env_file?.path || 'the env file'}. The next run will use these models.` });
            loadAllSettings();
        } catch (e) {
            setSaveMsg({ type: 'err', text: e.response?.data?.detail || 'Failed to save settings' });
        } finally {
            setSaving(false);
        }
    };

    const handleReset = () => {
        if (!settings) return;
        setDraft({
            stage1: settings.defaults.stage1, stage2: settings.defaults.stage2, summary: settings.defaults.summary, report: settings.defaults.report,
            stage2_threshold: settings.defaults.stage2_threshold, score_threshold: settings.defaults.score_threshold,
        });
    };

    const handleCfgSave = async () => {
        if (!Object.keys(cfgDraft).length) return;
        setCfgSaving(true); setCfgMsg(null); setCfgWarnings([]);
        try {
            const res = await axios.put(`${API_URL}/settings`, { values: cfgDraft });
            setAllSettings(res.data);
            setCfgDraft({});
            setShowSecret({});
            setCfgWarnings(res.data.warnings || []);
            const keys = Object.keys(res.data.applied || {}).filter(k => !k.startsWith('_'));
            setCfgMsg({ type: 'ok', text: keys.length ? `Saved ${keys.join(', ')} to ${res.data.env_file?.path}.` : 'Nothing to save.' });
            // provider / thresholds may have changed -> refresh the models card too
            loadAll();
        } catch (e) {
            setCfgMsg({ type: 'err', text: e.response?.data?.detail || 'Failed to save configuration' });
        } finally {
            setCfgSaving(false);
        }
    };

    const handleProfileSave = async () => {
        setProfileSaving(true); setProfileMsg(null);
        try {
            const res = await axios.put(`${API_URL}/settings/profile`, { profile: profileDraft });
            setSettings(s => ({ ...s, profile: res.data.profile }));
            setProfileMsg({ type: 'ok', text: `Saved. Used by the next scoring / summarization run.${(res.data.warnings || []).length ? ' ' + res.data.warnings.join(' ') : ''}` });
            loadAllSettings();
        } catch (e) {
            setProfileMsg({ type: 'err', text: e.response?.data?.detail || 'Failed to save profile' });
        } finally {
            setProfileSaving(false);
        }
    };

    const refreshCatalog = async () => {
        try {
            const res = await axios.get(`${API_URL}/models`, { params: { refresh: true } });
            setModels(res.data.models || []);
            setCatalogStatus(res.data.catalog || null);
        } catch (e) { console.error(e); }
    };

    const Card = ({ icon: Icon, title, children, right }) => (
        <section className="bg-slate-800 rounded-2xl border border-slate-700 shadow-xl overflow-hidden mb-8">
            <div className="flex items-center justify-between px-6 md:px-8 pt-6">
                <h3 className="flex items-center gap-2 text-xl font-bold text-slate-200"><Icon size={20} className="text-cyan-400" /> {title}</h3>
                {right}
            </div>
            <div className="p-6 md:p-8 pt-4">{children}</div>
        </section>
    );

    return (
        <div className="min-h-screen bg-[#0f172a] text-slate-200 p-6 md:p-12 font-sans selection:bg-cyan-500/30">
            <div className="max-w-4xl mx-auto">
                {/* Header */}
                <header className="flex items-center gap-4 mb-10">
                    <Link to="/" className="p-2 rounded-full bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700 transition-colors" title="Back to Home">
                        <ArrowLeft size={24} />
                    </Link>
                    <div className="flex items-center gap-3">
                        <SettingsIcon size={32} className="text-cyan-400" />
                        <h1 className="text-4xl font-black text-white">Settings</h1>
                    </div>
                </header>

                {loading ? (
                    <div className="animate-pulse space-y-4">
                        <div className="h-24 bg-slate-800 rounded-2xl"></div>
                        <div className="h-64 bg-slate-800 rounded-2xl"></div>
                    </div>
                ) : (
                    <>
                        {/* Provider + Models */}
                        <Card icon={Cpu} title="Models"
                            right={
                                <div className="text-xs text-slate-400 flex items-center gap-3">
                                    <span>
                                        Provider: <span className="font-mono text-slate-200">{settings?.provider?.name}</span>
                                        {' · '}
                                        {settings?.provider?.key_configured
                                            ? <span className="text-green-400">API key configured</span>
                                            : <span className="text-red-400">no API key</span>}
                                    </span>
                                    <button onClick={refreshCatalog} className="flex items-center gap-1 px-2 py-1 rounded bg-slate-700/60 hover:bg-slate-600 text-slate-300" title={`Catalog: ${catalogStatus?.count || 0} models${catalogStatus?.last_error ? ` · error: ${catalogStatus.last_error}` : ''}`}>
                                        <RefreshCw size={12} /> {catalogStatus?.count || 0} models
                                    </button>
                                </div>
                            }
                        >
                            {!models.length && (
                                <div className="flex items-start gap-2 text-sm text-yellow-300 bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 mb-5">
                                    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                                    <span>Model catalog unavailable ({catalogStatus?.last_error || 'not loaded'}). You can still type model ids, but prices and validation are disabled.</span>
                                </div>
                            )}
                            {models.length ? (
                                <>
                                    <ModelSelect label="Stage 1 · Screening" hint={TASK_META.score_stage1.hint} value={draft.stage1} onChange={v => setDraft(d => ({ ...d, stage1: v }))} models={models} />
                                    <ModelSelect label="Stage 2 · Review" hint={TASK_META.score_stage2.hint} value={draft.stage2} onChange={v => setDraft(d => ({ ...d, stage2: v }))} models={models} />
                                    <ModelSelect label="Summary" hint={TASK_META.summarize.hint} value={draft.summary} onChange={v => setDraft(d => ({ ...d, summary: v }))} models={models} />
                                    <ModelSelect label="Reports" hint={TASK_META.report.hint} value={draft.report} onChange={v => setDraft(d => ({ ...d, report: v }))} models={models} />
                                </>
                            ) : (
                                ['stage1', 'stage2', 'summary', 'report'].map(k => (
                                    <div key={k} className="mb-5">
                                        <label className="text-sm font-bold text-slate-200 block mb-1">{k}</label>
                                        <input value={draft[k]} onChange={e => setDraft(d => ({ ...d, [k]: e.target.value }))} className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 font-mono text-sm text-slate-200 focus:outline-none focus:border-cyan-500" />
                                    </div>
                                ))
                            )}

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
                                <div>
                                    <label className="text-sm font-bold text-slate-200 block mb-1">Stage-2 threshold</label>
                                    <p className="text-xs text-slate-500 mb-2">Stage-1 score needed to trigger the stage-2 review. Lower = more papers reviewed (higher recall, higher cost).</p>
                                    <input type="number" min="0" max="100" value={draft.stage2_threshold} onChange={e => setDraft(d => ({ ...d, stage2_threshold: e.target.value }))} className="w-32 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500" />
                                </div>
                                <div>
                                    <label className="text-sm font-bold text-slate-200 block mb-1">Score threshold</label>
                                    <p className="text-xs text-slate-500 mb-2">Final score needed to summarize + notify.</p>
                                    <input type="number" min="0" max="100" value={draft.score_threshold} onChange={e => setDraft(d => ({ ...d, score_threshold: e.target.value }))} className="w-32 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500" />
                                </div>
                            </div>

                            <div className="flex items-center gap-3 mt-8">
                                <button onClick={handleSave} disabled={!dirty || saving} className={`flex items-center gap-2 px-4 py-2 rounded-lg font-bold transition-colors ${!dirty || saving ? 'bg-slate-700 text-slate-500 cursor-not-allowed' : 'bg-cyan-500 hover:bg-cyan-400 text-slate-900'}`}>
                                    <Save size={16} /> {saving ? 'Saving…' : 'Save'}
                                </button>
                                <button onClick={handleReset} className="px-4 py-2 rounded-lg font-medium text-slate-300 hover:bg-slate-700 transition-colors">Reset to built-in defaults</button>
                                {saveMsg && (
                                    <span className={`text-sm ${saveMsg.type === 'ok' ? 'text-green-400' : 'text-red-400'}`}>{saveMsg.text}</span>
                                )}
                            </div>
                            {saveWarnings.length > 0 && <Warnings items={saveWarnings} />}
                            <p className="text-[11px] text-slate-500 mt-4 flex items-center gap-1.5">
                                <FileCog size={12} /> Stored in <code className="font-mono text-slate-400">{settings?.env_file?.path}</code>
                                {settings?.env_file && !settings.env_file.writable && <span className="text-red-400">(not writable!)</span>}
                                {' '}· changes apply to the next run, no restart needed.
                            </p>
                        </Card>

                        {/* Cost estimate */}
                        <Card icon={DollarSign} title="Estimated cost"
                            right={<span className="text-xs text-slate-500 flex items-center gap-1">{estimating && <RefreshCw size={12} className="animate-spin" />} for the selection above</span>}
                        >
                            {estimate ? (
                                <>
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                                        <Stat label="per day" value={fmtUSD(estimate.total_per_day, 3)} accent />
                                        <Stat label="per month" value={fmtUSD(estimate.total_per_month, 2)} accent />
                                        <Stat label="papers / day" value={estimate.per_task.find(t => t.task === 'score_stage1')?.calls_per_day ?? '—'} sub={estimate.per_task.find(t => t.task === 'score_stage1')?.volume_source === 'prior' ? 'prior (no recent papers)' : `observed · last ${estimate.volumes_meta?.window_days}d`} />
                                        <Stat label="stage-2 / summaries per day" value={`${estimate.per_task.find(t => t.task === 'score_stage2')?.calls_per_day ?? '—'} / ${estimate.per_task.find(t => t.task === 'summarize')?.calls_per_day ?? '—'}`} />
                                    </div>
                                    <div className="overflow-x-auto">
                                        <table className="w-full text-sm">
                                            <thead>
                                                <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-700">
                                                    <th className="py-2 pr-4">Task</th><th className="py-2 pr-4">Model</th><th className="py-2 pr-4 text-right">Tokens / call</th><th className="py-2 pr-4 text-right">Calls / day</th><th className="py-2 pr-4 text-right">$ / call</th><th className="py-2 text-right">$ / day</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {estimate.per_task.map(t => (
                                                    <tr key={t.task} className="border-b border-slate-800/60">
                                                        <td className="py-2 pr-4 text-slate-200">{TASK_META[t.task]?.label || t.task}</td>
                                                        <td className="py-2 pr-4 font-mono text-xs text-slate-300">{t.model}{t.price_in_per_m === null && <span className="text-yellow-400 ml-1" title="not in catalog">?</span>}</td>
                                                        <td className="py-2 pr-4 text-right font-mono text-xs text-slate-400" title={`${t.tokens_source}${t.token_samples ? ` · ${t.token_samples} samples` : ''}`}>{fmtNum(t.avg_prompt_tokens)} + {fmtNum(t.avg_completion_tokens)}<span className="text-slate-600"> {t.tokens_source === 'prior' ? '(prior)' : ''}</span></td>
                                                        <td className="py-2 pr-4 text-right font-mono text-xs text-slate-400">{t.calls_per_day}</td>
                                                        <td className="py-2 pr-4 text-right font-mono text-xs text-slate-300">{fmtUSD(t.cost_per_call, 5)}</td>
                                                        <td className="py-2 text-right font-mono text-xs text-slate-200">{fmtUSD(t.cost_per_day, 3)}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                    <p className="flex items-start gap-1.5 text-[11px] text-slate-500 mt-4"><Info size={12} className="mt-0.5 shrink-0" /> List prices from the provider catalog × average tokens per call (observed from your history when ≥5 samples, otherwise a prior) × observed daily volumes. Real spend is tracked below.</p>
                                </>
                            ) : (
                                <p className="text-sm text-slate-500">Select models to see an estimate.</p>
                            )}
                        </Card>

                        {/* Actual usage */}
                        <Card icon={Activity} title="Actual LLM spend"
                            right={<button onClick={loadUsage} className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-slate-700/60 hover:bg-slate-600 text-slate-300"><RefreshCw size={12} className={usageLoading ? 'animate-spin' : ''} /> refresh</button>}
                        >
                            {usage ? (
                                <>
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                                        {[['today', 'Today'], ['last_7d', 'Last 7 days'], ['last_30d', 'Last 30 days'], ['all_time', 'All time']].map(([k, label]) => (
                                            <Stat key={k} label={label} value={fmtUSD(usage.periods[k].cost, 3)} sub={`${fmtNum(usage.periods[k].calls)} calls · ${fmtNum(usage.periods[k].prompt_tokens + usage.periods[k].completion_tokens)} tok`} />
                                        ))}
                                    </div>
                                    {usage.breakdown.length ? (
                                        <div className="overflow-x-auto">
                                            <table className="w-full text-sm">
                                                <thead>
                                                    <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-700">
                                                        <th className="py-2 pr-4">Task</th><th className="py-2 pr-4">Model</th><th className="py-2 pr-4 text-right">Calls</th><th className="py-2 pr-4 text-right">Avg tokens</th><th className="py-2 pr-4 text-right">$ / call</th><th className="py-2 text-right">Cost ({usage.breakdown_days}d)</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {usage.breakdown.map((b, i) => (
                                                        <tr key={i} className="border-b border-slate-800/60">
                                                            <td className="py-2 pr-4 text-slate-200">{TASK_META[b.task]?.label || b.task}</td>
                                                            <td className="py-2 pr-4 font-mono text-xs text-slate-300">{b.model}</td>
                                                            <td className="py-2 pr-4 text-right font-mono text-xs text-slate-400">{fmtNum(b.calls)}</td>
                                                            <td className="py-2 pr-4 text-right font-mono text-xs text-slate-400">{fmtNum(b.avg_prompt_tokens)} + {fmtNum(b.avg_completion_tokens)}</td>
                                                            <td className="py-2 pr-4 text-right font-mono text-xs text-slate-300">{fmtUSD(b.cost_per_call, 5)}</td>
                                                            <td className="py-2 text-right font-mono text-xs text-slate-200">{fmtUSD(b.cost, 3)}{b.estimated_rows > 0 && <span className="text-slate-600" title={`${b.estimated_rows} calls had no reported cost; estimated from list price`}> ~</span>}</td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    ) : (
                                        <p className="text-sm text-slate-500">No LLM calls recorded yet. Usage is logged from the next run onward.</p>
                                    )}
                                </>
                            ) : (
                                <p className="text-sm text-slate-500">{usageLoading ? 'Loading…' : 'Usage unavailable.'}</p>
                            )}
                        </Card>

                        {/* Configuration (.env) */}
                        <Card icon={FileCog} title="Configuration"
                            right={allSettings && (
                                <span className="text-xs text-slate-500 flex items-center gap-2">
                                    <code className="font-mono text-slate-400">{allSettings.env_file.path}</code>
                                    {!allSettings.env_file.writable && <span className="text-red-400 font-bold">not writable</span>}
                                    <button onClick={loadAllSettings} className="flex items-center gap-1 px-2 py-1 rounded bg-slate-700/60 hover:bg-slate-600 text-slate-300"><RefreshCw size={12} /> reload</button>
                                </span>
                            )}
                        >
                            {!allSettings ? (
                                <p className="text-sm text-slate-500">Loading…</p>
                            ) : (
                                <>
                                    <p className="text-xs text-slate-500 mb-5 leading-relaxed">
                                        Every key of the env file, editable here. Saving rewrites only the changed keys (comments and other keys are preserved) and applies immediately — no restart.
                                        Secrets are never sent to the browser: leave a secret field blank to keep the current value, type a new one to replace it.
                                        A <span className="text-yellow-300">env var</span> badge means a process environment variable (e.g. docker-compose) overrides the file — edit it there instead.
                                    </p>
                                    {CONFIG_GROUPS.map(g => {
                                        const fields = allSettings.fields.filter(f => f.group === g.key && f.owner !== 'models');
                                        if (!fields.length) return null;
                                        return (
                                            <div key={g.key} className="mb-6">
                                                <h4 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-500 mb-3"><g.icon size={13} /> {g.label}</h4>
                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
                                                    {fields.map(f => (
                                                        <ConfigField key={f.key} field={f}
                                                            draftValue={cfgDraft[f.key]}
                                                            onChange={v => setCfgDraft(d => ({ ...d, [f.key]: v }))}
                                                            onRevert={() => setCfgDraft(d => { const n = { ...d }; delete n[f.key]; return n; })}
                                                            showSecret={!!showSecret[f.key]}
                                                            toggleSecret={() => setShowSecret(x => ({ ...x, [f.key]: !x[f.key] }))}
                                                        />
                                                    ))}
                                                </div>
                                            </div>
                                        );
                                    })}
                                    <div className="flex items-center gap-3 mt-2">
                                        <button onClick={handleCfgSave} disabled={!Object.keys(cfgDraft).length || cfgSaving} className={`flex items-center gap-2 px-4 py-2 rounded-lg font-bold transition-colors ${!Object.keys(cfgDraft).length || cfgSaving ? 'bg-slate-700 text-slate-500 cursor-not-allowed' : 'bg-cyan-500 hover:bg-cyan-400 text-slate-900'}`}>
                                            <Save size={16} /> {cfgSaving ? 'Saving…' : `Save${Object.keys(cfgDraft).length ? ` (${Object.keys(cfgDraft).length})` : ''}`}
                                        </button>
                                        {Object.keys(cfgDraft).length > 0 && <button onClick={() => { setCfgDraft({}); setShowSecret({}); }} className="px-4 py-2 rounded-lg font-medium text-slate-300 hover:bg-slate-700 transition-colors">Discard</button>}
                                        {cfgMsg && <span className={`text-sm ${cfgMsg.type === 'ok' ? 'text-green-400' : 'text-red-400'}`}>{cfgMsg.text}</span>}
                                    </div>
                                    {cfgWarnings.length > 0 && <Warnings items={cfgWarnings} />}
                                    {allSettings.scheduler?.next_run_time && (
                                        <p className="text-[11px] text-slate-500 mt-4 flex items-center gap-1.5"><Clock size={12} /> Next scheduled run: <span className="font-mono text-slate-400">{new Date(allSettings.scheduler.next_run_time).toLocaleString()}</span></p>
                                    )}
                                </>
                            )}
                        </Card>

                        {/* Profile */}
                        <Card icon={User} title="User Profile Prompt"
                            right={<span className="text-xs text-slate-500">{(profileDraft || '').length} chars</span>}
                        >
                            <p className="text-slate-400 mb-4 leading-relaxed text-sm">
                                Guides stage-1/stage-2 scoring (relevance tiers, exclusions) and the "Relevance to Me" section of summaries.
                                Saved to <code className="bg-slate-900 px-1.5 py-0.5 rounded text-cyan-400 font-mono text-xs border border-slate-700">USER_PROFILE</code> in the env file and used by the next run.
                                {settings?.summary_language && <> Summary language: <span className="font-mono text-slate-300">{settings.summary_language}</span> (change it in Configuration above).</>}
                            </p>
                            <textarea
                                value={profileDraft}
                                onChange={e => setProfileDraft(e.target.value)}
                                spellCheck={false}
                                className="w-full h-80 bg-slate-900 border border-slate-700 rounded-xl p-6 text-slate-300 font-mono text-sm focus:outline-none focus:border-cyan-500 resize-y shadow-inner leading-relaxed"
                            />
                            <div className="flex items-center gap-3 mt-4">
                                <button onClick={handleProfileSave} disabled={profileSaving || profileDraft === (settings?.profile || '')} className={`flex items-center gap-2 px-4 py-2 rounded-lg font-bold transition-colors ${profileSaving || profileDraft === (settings?.profile || '') ? 'bg-slate-700 text-slate-500 cursor-not-allowed' : 'bg-cyan-500 hover:bg-cyan-400 text-slate-900'}`}>
                                    <Save size={16} /> {profileSaving ? 'Saving…' : 'Save profile'}
                                </button>
                                {profileDraft !== (settings?.profile || '') && <button onClick={() => setProfileDraft(settings?.profile || '')} className="px-4 py-2 rounded-lg font-medium text-slate-300 hover:bg-slate-700 transition-colors">Discard</button>}
                                {profileMsg && <span className={`text-sm ${profileMsg.type === 'ok' ? 'text-green-400' : 'text-red-400'}`}>{profileMsg.text}</span>}
                            </div>
                        </Card>
                    </>
                )}
            </div>
        </div>
    );
}

const CONFIG_GROUPS = [
    { key: 'provider', label: 'LLM provider', icon: KeyRound },
    { key: 'pipeline', label: 'Pipeline', icon: Cpu },
    { key: 'schedule', label: 'Schedule', icon: Clock },
    { key: 'reports', label: 'Reports', icon: Activity },
    { key: 'notification', label: 'Notification', icon: Bell },
    { key: 'system', label: 'System (read-only)', icon: Database },
];

function SourceBadge({ field }) {
    if (field.source === 'env') return <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-300 border border-yellow-500/30" title={`Overridden by process environment variable ${field.env_var}`}>env var</span>;
    if (field.source === 'file') return <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300" title="Set in the env file">file</span>;
    return <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-500" title="Built-in default (not in the env file)">default</span>;
}

function Warnings({ items }) {
    return (
        <div className="mt-4 space-y-2">
            {items.map((w, i) => (
                <div key={i} className="flex items-start gap-2 text-xs text-yellow-300 bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3"><AlertTriangle size={14} className="mt-0.5 shrink-0" /><span>{w}</span></div>
            ))}
        </div>
    );
}

function ConfigField({ field, draftValue, onChange, onRevert, showSecret, toggleSecret }) {
    const dirty = draftValue !== undefined;
    const disabled = !field.editable;
    const base = `w-full bg-slate-900 border rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-cyan-500 ${dirty ? 'border-cyan-500/60' : 'border-slate-700'} ${disabled ? 'opacity-60 cursor-not-allowed' : ''}`;
    const current = field.value;
    let input;
    if (field.type === 'secret') {
        input = (
            <div className="relative">
                <input type={showSecret ? 'text' : 'password'} value={draftValue ?? ''} disabled={disabled} autoComplete="new-password"
                    onChange={e => onChange(e.target.value)}
                    placeholder={field.configured ? `configured (${field.hint}) — type to replace` : 'not configured — type to set'}
                    className={`${base} pr-9 font-mono`} />
                <button type="button" onClick={toggleSecret} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300" title={showSecret ? 'Hide' : 'Show typed value'}>{showSecret ? <EyeOff size={14} /> : <Eye size={14} />}</button>
            </div>
        );
    } else if (field.type === 'bool') {
        const val = dirty ? draftValue : !!current;
        input = (
            <label className={`inline-flex items-center gap-2 text-sm ${disabled ? 'opacity-60' : 'cursor-pointer'}`}>
                <input type="checkbox" checked={!!val} disabled={disabled} onChange={e => onChange(e.target.checked)} className="accent-cyan-500 w-4 h-4" />
                <span className="text-slate-300">{val ? 'enabled' : 'disabled'}</span>
            </label>
        );
    } else if (field.type === 'enum') {
        input = (
            <select value={dirty ? draftValue : (current ?? '')} disabled={disabled} onChange={e => onChange(e.target.value)} className={base}>
                {(field.options || []).map(o => <option key={o} value={o}>{o}</option>)}
            </select>
        );
    } else if (field.type === 'int') {
        input = <input type="number" min={field.min ?? undefined} max={field.max ?? undefined} value={dirty ? draftValue : (current ?? '')} disabled={disabled} onChange={e => onChange(e.target.value)} className={`${base} w-40`} />;
    } else if (field.type === 'list') {
        input = <input type="text" value={dirty ? draftValue : (Array.isArray(current) ? current.join(', ') : (current ?? ''))} disabled={disabled} onChange={e => onChange(e.target.value)} className={`${base} font-mono`} />;
    } else if (field.type === 'text') {
        input = <textarea value={dirty ? draftValue : (current ?? '')} disabled={disabled} onChange={e => onChange(e.target.value)} className={`${base} h-28 font-mono resize-y`} />;
    } else {
        input = <input type="text" value={dirty ? draftValue : (current ?? '')} disabled={disabled} onChange={e => onChange(e.target.value)} className={`${base} font-mono`} />;
    }
    return (
        <div className={field.type === 'text' ? 'md:col-span-2' : ''}>
            <div className="flex items-center justify-between mb-1">
                <label className="text-sm font-bold text-slate-200 flex items-center gap-2">{field.label}<SourceBadge field={field} /></label>
                <span className="flex items-center gap-2 text-[10px] font-mono text-slate-500">
                    {field.key}
                    {dirty && <button onClick={onRevert} className="text-cyan-400 hover:underline">revert</button>}
                </span>
            </div>
            {field.description && <p className="text-[11px] text-slate-500 mb-1.5">{field.description}</p>}
            {input}
            {field.source === 'env' && field.editable && <p className="text-[11px] text-yellow-400/80 mt-1">Overridden by environment variable <code>{field.env_var}</code> — saving here has no effect until it is removed from the container environment.</p>}
        </div>
    );
}

function Stat({ label, value, sub, accent }) {
    return (
        <div className="bg-slate-900/60 border border-slate-700/60 rounded-xl p-4">
            <div className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">{label}</div>
            <div className={`text-xl font-bold font-mono ${accent ? 'text-cyan-400' : 'text-slate-100'}`}>{value}</div>
            {sub && <div className="text-[11px] text-slate-500 mt-1">{sub}</div>}
        </div>
    );
}

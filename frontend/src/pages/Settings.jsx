import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { Settings as SettingsIcon, ArrowLeft, Activity, Save, RefreshCw, Search, AlertTriangle, FileCog, KeyRound, Clock, Database, User, Eye, EyeOff, Wallet, Flame, ChevronDown, FolderKanban, Send, Layers } from 'lucide-react';
import { Link } from 'react-router-dom';

const API_URL = '/api'; // All backend endpoints live under /api (same origin)

const TASK_META = {
    score_stage1: { label: '① Screen' },
    score_stage2: { label: '② Review' },
    summarize: { label: '③ Deep read' },
    translate: { label: 'Translation' },
    report: { label: 'Reports (removed)' },
    hot_chatter: { label: 'Hot · web search' },
    embed: { label: 'Embeddings' },
    affiliation: { label: 'Affiliation (legacy)' },
};

const fmtUSD = (v, digits = 4) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : `$${Number(v).toFixed(digits)}`;
const fmtNum = (v) => (v === null || v === undefined) ? '—' : Number(v).toLocaleString();

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */
export default function Settings() {
    const [loading, setLoading] = useState(true);
    const [settings, setSettings] = useState(null);


    const [usage, setUsage] = useState(null);
    const [usageLoading, setUsageLoading] = useState(true);

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

    // embeddings coverage / backfill
    const [embStatus, setEmbStatus] = useState(null);
    const [embBusy, setEmbBusy] = useState(false);
    const loadEmb = useCallback(async () => {
        try { const res = await axios.get(`${API_URL}/embeddings/status`); setEmbStatus(res.data); } catch (e) { console.error(e); }
    }, []);
    const startBackfill = async () => {
        setEmbBusy(true);
        try { const res = await axios.post(`${API_URL}/embeddings/backfill`); setEmbStatus(res.data); } catch (e) { alert(e.response?.data?.detail || 'Backfill failed'); } finally { setEmbBusy(false); }
    };
    useEffect(() => {
        if (!embStatus?.backfill?.running) return;
        const t = setInterval(loadEmb, 3000);
        return () => clearInterval(t);
    }, [embStatus?.backfill?.running, loadEmb]);

    // Claude (verdict pipeline)
    const [claudeModels, setClaudeModels] = useState([]);
    const [budget, setBudget] = useState(null);
    const loadClaude = useCallback(async () => {
        try {
            const [m, b] = await Promise.all([axios.get(`${API_URL}/claude/models`), axios.get(`${API_URL}/claude/budget`)]);
            setClaudeModels(m.data.models || []); setBudget(b.data);
        } catch (e) { console.error(e); }
    }, []);

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
            const sRes = await axios.get(`${API_URL}/settings/llm`);
            setSettings(sRes.data);
            setProfileDraft(sRes.data.profile || '');
        } catch (e) {
            console.error('Failed to load settings', e);
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

    useEffect(() => { loadAll(); loadUsage(); loadAllSettings(); loadEmb(); loadClaude(); }, [loadAll, loadUsage, loadAllSettings, loadEmb, loadClaude]);

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
            loadAll(); loadClaude();
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


    // ---- helpers for the env-backed fields --------------------------------------------------------
    const fieldByKey = Object.fromEntries((allSettings?.fields || []).map(f => [f.key, f]));
    const valueOf = (k) => (cfgDraft[k] !== undefined ? cfgDraft[k] : fieldByKey[k]?.value);
    const anthropicOk = !!fieldByKey.ANTHROPIC_API_KEY?.configured;
    const openrouterOk = !!fieldByKey.OPENROUTER_API_KEY?.configured;
    const chatProvider = valueOf('CHAT_PROVIDER') || 'anthropic';
    const chatOk = chatProvider === 'openrouter' ? openrouterOk : anthropicOk;
    const nDirty = Object.keys(cfgDraft).length;

    const F = (key, extra = {}) => {
        const f = fieldByKey[key];
        if (!f) return null;
        const field = { ...f, ...extra };
        return (
            <ConfigField key={key} field={field}
                draftValue={cfgDraft[key]}
                onChange={v => setCfgDraft(d => ({ ...d, [key]: v }))}
                onRevert={() => setCfgDraft(d => { const n = { ...d }; delete n[key]; return n; })}
                showSecret={!!showSecret[key]}
                toggleSecret={() => setShowSecret(x => ({ ...x, [key]: !x[key] }))}
            />
        );
    };

    const ClaudeModel = (key, label, hint) => {
        const f = fieldByKey[key];
        if (!f) return null;
        const val = valueOf(key) || '';
        const known = claudeModels.find(m => m.id === val);
        const dirty = cfgDraft[key] !== undefined;
        return (
            <div key={key}>
                <div className="flex items-baseline justify-between mb-1">
                    <label className="text-sm font-bold text-slate-200">{label}</label>
                    {known && <span className="text-[11px] font-mono text-slate-500">${known.prompt_price_per_m} in / ${known.completion_price_per_m} out per 1M</span>}
                </div>
                <p className="text-[11px] text-slate-500 mb-1.5">{hint}</p>
                <select value={val} onChange={e => setCfgDraft(d => ({ ...d, [key]: e.target.value }))}
                    className={`w-full bg-slate-900 border rounded-lg px-3 py-2 text-sm font-mono text-slate-200 focus:outline-none focus:border-cyan-500 ${dirty ? 'border-cyan-500/60' : 'border-slate-700'}`}>
                    {!known && <option value={val}>{val || '— select —'} {val ? '(not a Claude model)' : ''}</option>}
                    {claudeModels.map(m => <option key={m.id} value={m.id}>{m.id} · {m.name}</option>)}
                </select>
            </div>
        );
    };

    const spentPct = budget ? Math.min(100, Math.round(100 * budget.spent / Math.max(1, budget.budget))) : 0;

    return (
        <div className="min-h-screen bg-[#0f172a] text-slate-200 p-6 md:p-12 pb-32 font-sans selection:bg-cyan-500/30">
            <div className="max-w-4xl mx-auto">
                {/* Header */}
                <header className="flex items-center gap-4 mb-6">
                    <Link to="/" className="p-2 rounded-full bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700 transition-colors" title="Back to Home">
                        <ArrowLeft size={24} />
                    </Link>
                    <div className="flex items-center gap-3">
                        <SettingsIcon size={32} className="text-cyan-400" />
                        <h1 className="text-4xl font-black text-white">Settings</h1>
                    </div>
                </header>

                {loading || !allSettings ? (
                    <div className="animate-pulse space-y-4">
                        <div className="h-24 bg-slate-800 rounded-2xl"></div>
                        <div className="h-64 bg-slate-800 rounded-2xl"></div>
                    </div>
                ) : (
                    <>
                        {/* Status strip */}
                        <div className="flex flex-wrap items-center gap-2 mb-8">
                            <span className="text-sm text-slate-400 mr-1">Chat models via</span>
                            <div className="inline-flex rounded-lg border border-slate-700 overflow-hidden mr-2">
                                {[['anthropic', 'Claude API'], ['openrouter', 'OpenRouter']].map(([v, label]) => (
                                    <button key={v} onClick={() => setCfgDraft(d => ({ ...d, CHAT_PROVIDER: v }))}
                                        className={`px-3 py-1.5 text-sm font-bold ${chatProvider === v ? 'bg-cyan-500 text-slate-900' : 'bg-slate-800 text-slate-400 hover:text-slate-200'}`}>{label}</button>
                                ))}
                            </div>
                            <Chip ok={chatOk}>{chatProvider === 'openrouter' ? 'OpenRouter key' : 'Anthropic key'} {chatOk ? 'configured' : 'missing'}</Chip>
                            <Chip ok={openrouterOk}>Embeddings → OpenRouter {openrouterOk ? '' : '(no key)'}</Chip>
                            {budget && <Chip ok={budget.remaining > 0}>${budget.spent.toFixed(2)} / ${budget.budget} this cycle</Chip>}
                        </div>

                                {settings?.warnings?.length > 0 && <div className="-mt-4 mb-6"><Warnings items={settings.warnings} /></div>}
                                {/* Pipeline */}
                                <Card icon={Layers} title="Pipeline">
                                    <p className="text-xs text-slate-500 mb-5">Every new paper → ① Screen (relevance tier) → ② Review of the relevant ones (verdict + affiliations) → ③ Deep read of Must Read / Worth Reading papers (final verdict, TL;DR, paragraph notes, claim flags) + translation.</p>
                                    <Grid>
                                        {ClaudeModel('LLM_MODEL_STAGE1', '① Screen', 'Title + abstract of every new paper → relevance 0-5.')}
                                        {ClaudeModel('LLM_MODEL_STAGE2', '② Review', 'Abstract + first part of the paper → verdict, affiliations, project matches.')}
                                        {ClaudeModel('LLM_MODEL_SUMMARY', '③ Deep read', 'Whole paper → final verdict, TL;DR, paragraph notes, claim flags.')}
                                        {ClaudeModel('LLM_MODEL_TRANSLATE', 'Translation', 'Full Chinese translation for the reading page.')}
                                        {F('SUMMARY_LANGUAGE', { label: 'TL;DR and notes language' })}
                                        {F('SCREEN_MIN_RELEVANCE', { label: 'Review papers with relevance ≥', description: 'Screen tier needed to go on to review (4 = strong interest or core).' })}
                                        {F('DEEP_READ_MAX_PER_RUN')}
                                        {F('STAGE2_TEXT_CHAR_LIMIT', { label: 'Review excerpt (chars)', description: 'How much of the paper the reviewer sees.' })}
                                    </Grid>
                                </Card>

                                {/* Budget */}
                                <Card icon={Wallet} title="Budget & batch">
                                    {budget && (
                                        <div className="mb-6">
                                            <div className="flex items-baseline justify-between text-sm mb-1.5">
                                                <span className="text-slate-300">Spent this cycle (since {new Date(budget.cycle_start).toLocaleDateString()})</span>
                                                <span className="font-mono text-slate-200">${budget.spent.toFixed(2)} / ${budget.budget}</span>
                                            </div>
                                            <div className="h-2 rounded-full bg-slate-900 overflow-hidden"><div className={`h-full ${spentPct > 90 ? 'bg-red-400' : 'bg-cyan-500'}`} style={{ width: `${spentPct}%` }} /></div>
                                            <p className="text-[11px] text-slate-500 mt-1.5">List-price estimate from the call log. When it is used up, stages are trimmed or skipped and the papers wait for the next cycle; on-demand deep reads are refused.</p>
                                        </div>
                                    )}
                                    <Grid>
                                        {F('CLAUDE_MONTHLY_BUDGET')}
                                        {F('CLAUDE_BUDGET_RESET_DAY')}
                                        {F('LLM_USE_BATCH', chatProvider === 'openrouter' ? { description: 'Claude API only — OpenRouter has no Batch API, so calls run in real time (full price).' } : {})}
                                        {F('BATCH_MAX_WAIT_MINUTES')}
                                    </Grid>
                                </Card>

                        {/* Profile & sources */}
                        <Card icon={User} title="What to look for"
                            right={<Link to="/projects" className="flex items-center gap-1.5 text-xs px-2 py-1 rounded bg-slate-700/60 hover:bg-slate-600 text-slate-300"><FolderKanban size={12} /> Projects</Link>}>
                            <div className="mb-5">
                                <div className="flex items-baseline justify-between mb-1">
                                    <label className="text-sm font-bold text-slate-200">Research profile</label>
                                    <span className="text-[11px] text-slate-500">{(profileDraft || '').length} chars</span>
                                </div>
                                <p className="text-[11px] text-slate-500 mb-1.5">Core / strong interests, methodological angles, decision rules and exclusions. Every stage judges relevance against this.</p>
                                <textarea value={profileDraft} onChange={e => setProfileDraft(e.target.value)} spellCheck={false}
                                    className="w-full h-72 bg-slate-900 border border-slate-700 rounded-xl p-4 text-slate-300 font-mono text-[13px] focus:outline-none focus:border-cyan-500 resize-y leading-relaxed" />
                                <div className="flex items-center gap-3 mt-3">
                                    <button onClick={handleProfileSave} disabled={profileSaving || profileDraft === (settings?.profile || '')} className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-bold ${profileSaving || profileDraft === (settings?.profile || '') ? 'bg-slate-700 text-slate-500 cursor-not-allowed' : 'bg-cyan-500 hover:bg-cyan-400 text-slate-900'}`}><Save size={14} /> {profileSaving ? 'Saving…' : 'Save profile'}</button>
                                    {profileDraft !== (settings?.profile || '') && <button onClick={() => setProfileDraft(settings?.profile || '')} className="px-3 py-1.5 rounded-lg text-sm text-slate-300 hover:bg-slate-700">Discard</button>}
                                    {profileMsg && <span className={`text-sm ${profileMsg.type === 'ok' ? 'text-green-400' : 'text-red-400'}`}>{profileMsg.text}</span>}
                                </div>
                            </div>
                            <Grid>
                                {F('ARXIV_CATEGORIES')}
                                {F('PROJECT_SIM_THRESHOLD', { label: 'Project recall threshold' })}
                            </Grid>
                        </Card>

                        {/* Hot lane */}
                        <Card icon={Flame} title="Hot papers">
                            <p className="text-xs text-slate-500 mb-5">Popular papers from Hugging Face Daily Papers get their own section in the digest — relevant or not — each pushed once.</p>
                            <Grid>
                                {F('HOT_ENABLED', { label: 'Hot section' })}
                                {F('HOT_MAX_PER_RUN', { label: 'Papers per digest' })}
                                {F('HOT_MIN_UPVOTES', { label: 'Minimum upvotes' })}
                                {F('HOT_MIN_STARS', { label: 'or minimum GitHub stars' })}
                                {F('HOT_LOOKBACK_DAYS', { label: 'Look back (days)' })}
                                {F('HOT_WEB_SEARCH', { label: 'Web search for discussion' })}
                            </Grid>
                        </Card>

                        {/* Delivery */}
                        <Card icon={Send} title="Schedule & notifications">
                            <Grid>
                                {F('ENABLE_AUTO_UPDATE')}
                                {F('AUTO_UPDATE_TIME')}
                                {F('LARK_WEBHOOK_URL')}
                                {F('PUBLIC_BASE_URL')}
                            </Grid>
                            {allSettings.scheduler?.next_run_time && (
                                <p className="text-[11px] text-slate-500 mt-5 flex items-center gap-1.5"><Clock size={12} /> Next scheduled run: <span className="font-mono text-slate-400">{new Date(allSettings.scheduler.next_run_time).toLocaleString()}</span></p>
                            )}
                        </Card>

                        {/* Keys */}
                        <Card icon={KeyRound} title="API keys">
                            <p className="text-xs text-slate-500 mb-5">Secrets are never sent to the browser: leave a field blank to keep the current key, type a new one to replace it.</p>
                            <Grid>
                                {F('ANTHROPIC_API_KEY', { description: 'Claude Console key — chat models when "Claude API" is selected (Batch API, subscription credits).' })}
                                {F('OPENROUTER_API_KEY', { description: 'Embeddings (always), and chat models when "OpenRouter" is selected.' })}
                            </Grid>
                            <details className="mt-5 group">
                                <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-300 flex items-center gap-1"><ChevronDown size={12} className="group-open:rotate-180 transition-transform" /> OpenRouter endpoint</summary>
                                <div className="mt-4"><Grid>{F('OPENROUTER_BASE_URL')}</Grid></div>
                            </details>
                        </Card>

                        {/* Spend */}
                        <Card icon={Activity} title="LLM spend"
                            right={<button onClick={loadUsage} className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-slate-700/60 hover:bg-slate-600 text-slate-300"><RefreshCw size={12} className={usageLoading ? 'animate-spin' : ''} /> refresh</button>}>
                            {usage ? (
                                <>
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                                        {[['today', 'Today'], ['last_7d', 'Last 7 days'], ['last_30d', 'Last 30 days'], ['all_time', 'All time']].map(([k, label]) => (
                                            <Stat key={k} label={label} value={fmtUSD(usage.periods[k].cost, 3)} sub={`${fmtNum(usage.periods[k].calls)} calls`} />
                                        ))}
                                    </div>
                                    {usage.breakdown.length ? (
                                        <div className="overflow-x-auto">
                                            <table className="w-full text-sm">
                                                <thead>
                                                    <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-slate-700">
                                                        <th className="py-2 pr-4">Task</th><th className="py-2 pr-4">Model</th><th className="py-2 pr-4 text-right">Calls</th><th className="py-2 pr-4 text-right">$ / call</th><th className="py-2 text-right">Cost ({usage.breakdown_days}d)</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {usage.breakdown.map((b, i) => (
                                                        <tr key={i} className="border-b border-slate-800/60">
                                                            <td className="py-2 pr-4 text-slate-200">{TASK_META[b.task]?.label || b.task}</td>
                                                            <td className="py-2 pr-4 font-mono text-xs text-slate-300">{b.model}</td>
                                                            <td className="py-2 pr-4 text-right font-mono text-xs text-slate-400">{fmtNum(b.calls)}</td>
                                                            <td className="py-2 pr-4 text-right font-mono text-xs text-slate-300">{fmtUSD(b.cost_per_call, 5)}</td>
                                                            <td className="py-2 text-right font-mono text-xs text-slate-200">{fmtUSD(b.cost, 3)}</td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    ) : <p className="text-sm text-slate-500">No LLM calls recorded yet.</p>}
                                </>
                            ) : <p className="text-sm text-slate-500">{usageLoading ? 'Loading…' : 'Usage unavailable.'}</p>}
                        </Card>

                        {/* Advanced */}
                        <details className="group bg-slate-800/60 rounded-2xl border border-slate-700 mb-8">
                            <summary className="cursor-pointer px-6 md:px-8 py-5 flex items-center gap-2 text-lg font-bold text-slate-300"><ChevronDown size={18} className="group-open:rotate-180 transition-transform text-cyan-400" /> Advanced</summary>
                            <div className="px-6 md:px-8 pb-8 space-y-8">
                                <div>
                                    <h4 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-500 mb-3"><Search size={13} /> Embeddings</h4>
                                    {embStatus && (
                                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                                            <Stat label="model" value={<span className="text-sm">{embStatus.model}</span>} sub={`${embStatus.dim} dims`} />
                                            <Stat label="embedded" value={fmtNum(embStatus.embedded)} sub={`of ${fmtNum(embStatus.total_papers)} papers`} accent />
                                            <Stat label="missing" value={fmtNum(embStatus.missing)} />
                                            <Stat label="index in memory" value={fmtNum(embStatus.index_size)} />
                                        </div>
                                    )}
                                    {embStatus && (
                                        <button onClick={startBackfill} disabled={embBusy || embStatus.backfill?.running || !embStatus.missing} className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-bold mb-4 ${embBusy || embStatus.backfill?.running || !embStatus.missing ? 'bg-slate-700 text-slate-500 cursor-not-allowed' : 'bg-cyan-500 hover:bg-cyan-400 text-slate-900'}`}>
                                            <RefreshCw size={14} className={embStatus.backfill?.running ? 'animate-spin' : ''} /> {embStatus.backfill?.running ? `Backfilling ${fmtNum(embStatus.backfill.done)} / ${fmtNum(embStatus.backfill.total)}…` : (embStatus.missing ? `Backfill ${fmtNum(embStatus.missing)} papers` : 'All papers embedded')}
                                        </button>
                                    )}
                                    <Grid>{F('EMBEDDING_MODEL')}{F('EMBEDDING_DIM')}</Grid>
                                </div>
                                <div>
                                    <h4 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-500 mb-3"><Database size={13} /> System (read-only)</h4>
                                    <Grid>{F('DATABASE_URL')}{F('DEV_COMMIT')}</Grid>
                                    <p className="text-[11px] text-slate-500 mt-4 flex items-center gap-1.5"><FileCog size={12} /> Settings are stored in <code className="font-mono text-slate-400">{allSettings.env_file.path}</code>{!allSettings.env_file.writable && <span className="text-red-400"> (not writable!)</span>} and apply to the next run without a restart.</p>
                                </div>
                            </div>
                        </details>
                    </>
                )}
            </div>

            {/* Sticky save bar for env-backed settings */}
            {(nDirty > 0 || cfgMsg) && (
                <div className="fixed bottom-0 inset-x-0 z-40 bg-slate-900/95 backdrop-blur border-t border-slate-700">
                    <div className="max-w-4xl mx-auto px-6 py-3 flex flex-wrap items-center gap-3">
                        {nDirty > 0 && (
                            <>
                                <span className="text-sm text-slate-300">{nDirty} unsaved change{nDirty > 1 ? 's' : ''}: <span className="font-mono text-xs text-slate-500">{Object.keys(cfgDraft).join(', ')}</span></span>
                                <button onClick={handleCfgSave} disabled={cfgSaving} className="ml-auto flex items-center gap-2 px-4 py-2 rounded-lg font-bold bg-cyan-500 hover:bg-cyan-400 text-slate-900"><Save size={16} /> {cfgSaving ? 'Saving…' : 'Save'}</button>
                                <button onClick={() => { setCfgDraft({}); setShowSecret({}); }} className="px-4 py-2 rounded-lg font-medium text-slate-300 hover:bg-slate-700">Discard</button>
                            </>
                        )}
                        {cfgMsg && nDirty === 0 && <span className={`text-sm ${cfgMsg.type === 'ok' ? 'text-green-400' : 'text-red-400'}`}>{cfgMsg.text}</span>}
                        {cfgWarnings.length > 0 && <div className="w-full"><Warnings items={cfgWarnings} /></div>}
                    </div>
                </div>
            )}
        </div>
    );
}

function Card({ icon: Icon, title, children, right }) {
    return (
        <section className="bg-slate-800 rounded-2xl border border-slate-700 shadow-xl overflow-hidden mb-8">
            <div className="flex items-center justify-between px-6 md:px-8 pt-6">
                <h3 className="flex items-center gap-2 text-xl font-bold text-slate-200"><Icon size={20} className="text-cyan-400" /> {title}</h3>
                {right}
            </div>
            <div className="p-6 md:p-8 pt-4">{children}</div>
        </section>
    );
}

function Grid({ children }) {
    return <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">{children}</div>;
}

function Chip({ ok, children }) {
    return (
        <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border ${ok ? 'bg-green-500/10 text-green-300 border-green-500/30' : 'bg-red-500/10 text-red-300 border-red-500/30'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-green-400' : 'bg-red-400'}`} />{children}
        </span>
    );
}

function SourceBadge({ field }) {
    // Only the case that changes behaviour is shown: a process env var overrides the env file.
    if (field.source !== 'env') return null;
    return <span className="shrink-0 whitespace-nowrap text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-300 border border-yellow-500/30" title={`Overridden by process environment variable ${field.env_var}`}>env var</span>;
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
                {(field.options || []).map((o, i) => <option key={o} value={o}>{field.optionLabels?.[i] ?? o}</option>)}
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
            <div className="flex items-center justify-between gap-3 mb-1">
                <label className="text-sm font-bold text-slate-200 flex items-center gap-2 min-w-0" title={field.key}>
                    <span>{field.label}</span><SourceBadge field={field} />
                </label>
                {dirty && <button onClick={onRevert} className="shrink-0 text-[11px] text-cyan-400 hover:underline">revert</button>}
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

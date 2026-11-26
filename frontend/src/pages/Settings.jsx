import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { Activity, Save, RefreshCw, Search, AlertTriangle, FileCog, KeyRound, Clock, Database, User, Eye, EyeOff, Wallet, Flame, ChevronDown, FolderKanban, Send, Layers } from 'lucide-react';
import { Link } from 'react-router-dom';
import TopBar from '../components/TopBar';

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
            <div key={key} className="pa-field">
                <div className="lbl">
                    <label>{label}</label>
                    {known && <span className="price">${known.prompt_price_per_m} in / ${known.completion_price_per_m} out per 1M</span>}
                </div>
                <p className="desc">{hint}</p>
                <select value={val} onChange={e => setCfgDraft(d => ({ ...d, [key]: e.target.value }))}
                    className={`pa-input mono ${dirty ? 'dirty' : ''}`}>
                    {!known && <option value={val}>{val || '— select —'} {val ? '(not a Claude model)' : ''}</option>}
                    {claudeModels.map(m => <option key={m.id} value={m.id}>{m.id} · {m.name}</option>)}
                </select>
            </div>
        );
    };

    const spentPct = budget ? Math.min(100, Math.round(100 * budget.spent / Math.max(1, budget.budget))) : 0;
    const profileDirty = profileDraft !== (settings?.profile || '');

    return (
        <div className="pa">
            <TopBar />

            <main className="pa-main pa-doc pa-settings">
                <section className="pa-hero">
                    <div className="pa-kicker">Models, budget, research profile and schedule · saved to the env file</div>
                    <h1>Settings</h1>
                    {!loading && allSettings && (
                        <div className="pa-controls pa-status">
                            <span className="pa-meta">Chat models via</span>
                            <div className="pa-tabs" role="group" aria-label="Chat provider">
                                {[['anthropic', 'Claude API'], ['openrouter', 'OpenRouter']].map(([v, label]) => (
                                    <button key={v} type="button" onClick={() => setCfgDraft(d => ({ ...d, CHAT_PROVIDER: v }))}
                                        className={chatProvider === v ? 'on' : ''}>{label}</button>
                                ))}
                            </div>
                            <Chip ok={chatOk}>{chatProvider === 'openrouter' ? 'OpenRouter key' : 'Anthropic key'} {chatOk ? 'configured' : 'missing'}</Chip>
                            <Chip ok={openrouterOk}>Embeddings → OpenRouter {openrouterOk ? '' : '(no key)'}</Chip>
                            {budget && <Chip ok={budget.remaining > 0}>${budget.spent.toFixed(2)} / ${budget.budget} this cycle</Chip>}
                        </div>
                    )}
                </section>

                {loading || !allSettings ? (
                    <div className="pa-sentinel"><RefreshCw className="animate-spin" size={22} /></div>
                ) : (
                    <>
                        {settings?.warnings?.length > 0 && <Warnings items={settings.warnings} />}

                        {/* Pipeline */}
                        <Card icon={<Layers size={18} />} title="Pipeline">
                            <p className="pa-help">Every new paper → ① Screen (relevance tier) → ② Review of the relevant ones (verdict + affiliations) → ③ Deep read of Must Read / Worth Reading papers (final verdict, TL;DR, paragraph notes, claim flags) + translation.</p>
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
                        <Card icon={<Wallet size={18} />} title="Budget & batch">
                            {budget && (
                                <div className="pa-budget">
                                    <div className="lbl">
                                        <span>Spent this cycle (since {new Date(budget.cycle_start).toLocaleDateString()})</span>
                                        <b>${budget.spent.toFixed(2)} / ${budget.budget}</b>
                                    </div>
                                    <div className={`bar ${spentPct > 90 ? 'over' : ''}`}><span style={{ width: `${spentPct}%` }} /></div>
                                    <p className="desc">List-price estimate from the call log. When it is used up, stages are trimmed or skipped and the papers wait for the next cycle; on-demand deep reads are refused.</p>
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
                        <Card icon={<User size={18} />} title="What to look for"
                            right={<Link to="/projects" className="pa-btn small"><FolderKanban size={12} /> Projects</Link>}>
                            <div className="pa-field pa-profile">
                                <div className="lbl">
                                    <label htmlFor="research-profile">Research profile</label>
                                    <span className="price">{(profileDraft || '').length} chars</span>
                                </div>
                                <p className="desc">Core / strong interests, methodological angles, decision rules and exclusions. Every stage judges relevance against this.</p>
                                <textarea id="research-profile" value={profileDraft} onChange={e => setProfileDraft(e.target.value)} spellCheck={false}
                                    className="pa-input mono" />
                                <div className="pa-row">
                                    <button type="button" onClick={handleProfileSave} disabled={profileSaving || !profileDirty} className="pa-btn primary"><Save size={14} /> {profileSaving ? 'Saving…' : 'Save profile'}</button>
                                    {profileDirty && <button type="button" onClick={() => setProfileDraft(settings?.profile || '')} className="pa-btn">Discard</button>}
                                    {profileMsg && <span className={`pa-flash ${profileMsg.type}`}>{profileMsg.text}</span>}
                                </div>
                            </div>
                            <Grid>
                                {F('ARXIV_CATEGORIES')}
                                {F('PROJECT_SIM_THRESHOLD', { label: 'Project recall threshold' })}
                            </Grid>
                        </Card>

                        {/* Hot lane */}
                        <Card icon={<Flame size={18} />} title="Hot papers">
                            <p className="pa-help">Popular papers from Hugging Face Daily Papers get their own section in the digest — relevant or not — each pushed once.</p>
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
                        <Card icon={<Send size={18} />} title="Schedule & notifications">
                            <Grid>
                                {F('ENABLE_AUTO_UPDATE')}
                                {F('AUTO_UPDATE_TIME')}
                                {F('LARK_WEBHOOK_URL')}
                                {F('PUBLIC_BASE_URL')}
                            </Grid>
                            {allSettings.scheduler?.next_run_time && (
                                <p className="pa-help foot"><Clock size={12} /> Next scheduled run: <code>{new Date(allSettings.scheduler.next_run_time).toLocaleString()}</code></p>
                            )}
                        </Card>

                        {/* Keys */}
                        <Card icon={<KeyRound size={18} />} title="API keys">
                            <p className="pa-help">Secrets are never sent to the browser: leave a field blank to keep the current key, type a new one to replace it.</p>
                            <Grid>
                                {F('ANTHROPIC_API_KEY', { description: 'Claude Console key — chat models when "Claude API" is selected (Batch API, subscription credits).' })}
                                {F('OPENROUTER_API_KEY', { description: 'Embeddings (always), and chat models when "OpenRouter" is selected.' })}
                            </Grid>
                            <details className="pa-more-box">
                                <summary><ChevronDown size={12} className="chev" /> OpenRouter endpoint</summary>
                                <div className="in"><Grid>{F('OPENROUTER_BASE_URL')}</Grid></div>
                            </details>
                        </Card>

                        {/* Spend */}
                        <Card icon={<Activity size={18} />} title="LLM spend"
                            right={<button type="button" onClick={loadUsage} className="pa-btn small"><RefreshCw size={12} className={usageLoading ? 'animate-spin' : ''} /> Refresh</button>}>
                            {usage ? (
                                <>
                                    <div className="pa-stats">
                                        {[['today', 'Today'], ['last_7d', 'Last 7 days'], ['last_30d', 'Last 30 days'], ['all_time', 'All time']].map(([k, label]) => (
                                            <Stat key={k} label={label} value={fmtUSD(usage.periods[k].cost, 3)} sub={`${fmtNum(usage.periods[k].calls)} calls`} />
                                        ))}
                                    </div>
                                    {usage.breakdown.length ? (
                                        <div className="pa-table-wrap">
                                            <table className="pa-table">
                                                <thead>
                                                    <tr>
                                                        <th>Task</th><th>Model</th><th className="r">Calls</th><th className="r">$ / call</th><th className="r">Cost ({usage.breakdown_days}d)</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {usage.breakdown.map((b, i) => (
                                                        <tr key={i}>
                                                            <td>{TASK_META[b.task]?.label || b.task}</td>
                                                            <td className="mono">{b.model}</td>
                                                            <td className="r mono">{fmtNum(b.calls)}</td>
                                                            <td className="r mono">{fmtUSD(b.cost_per_call, 5)}</td>
                                                            <td className="r mono strong">{fmtUSD(b.cost, 3)}</td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    ) : <p className="pa-meta">No LLM calls recorded yet.</p>}
                                </>
                            ) : <p className="pa-meta">{usageLoading ? 'Loading…' : 'Usage unavailable.'}</p>}
                        </Card>

                        {/* Advanced */}
                        <details className="pa-section pa-adv">
                            <summary><ChevronDown size={18} className="chev" /> Advanced</summary>
                            <div className="pa-adv-body">
                                <div>
                                    <h4><Search size={13} /> Embeddings</h4>
                                    {embStatus && (
                                        <div className="pa-stats">
                                            <Stat label="model" value={<span className="small">{embStatus.model}</span>} sub={`${embStatus.dim} dims`} />
                                            <Stat label="embedded" value={fmtNum(embStatus.embedded)} sub={`of ${fmtNum(embStatus.total_papers)} papers`} accent />
                                            <Stat label="missing" value={fmtNum(embStatus.missing)} />
                                            <Stat label="index in memory" value={fmtNum(embStatus.index_size)} />
                                        </div>
                                    )}
                                    {embStatus && (
                                        <div className="pa-row">
                                            <button type="button" onClick={startBackfill} disabled={embBusy || embStatus.backfill?.running || !embStatus.missing} className="pa-btn primary">
                                                <RefreshCw size={14} className={embStatus.backfill?.running ? 'animate-spin' : ''} /> {embStatus.backfill?.running ? `Backfilling ${fmtNum(embStatus.backfill.done)} / ${fmtNum(embStatus.backfill.total)}…` : (embStatus.missing ? `Backfill ${fmtNum(embStatus.missing)} papers` : 'All papers embedded')}
                                            </button>
                                        </div>
                                    )}
                                    <Grid>{F('EMBEDDING_MODEL')}{F('EMBEDDING_DIM')}</Grid>
                                </div>
                                <div>
                                    <h4><Database size={13} /> System (read-only)</h4>
                                    <Grid>{F('DATABASE_URL')}{F('DEV_COMMIT')}</Grid>
                                    <p className="pa-help foot"><FileCog size={12} /> <span>Settings are stored in <code>{allSettings.env_file.path}</code>{!allSettings.env_file.writable && <span className="bad"> (not writable!)</span>} and apply to the next run without a restart.</span></p>
                                </div>
                            </div>
                        </details>
                    </>
                )}
            </main>

            {/* Sticky save bar for env-backed settings */}
            {(nDirty > 0 || cfgMsg) && (
                <div className="pa-savebar">
                    <div className="in">
                        {nDirty > 0 && (
                            <>
                                <span className="what">{nDirty} unsaved change{nDirty > 1 ? 's' : ''}: <code>{Object.keys(cfgDraft).join(', ')}</code></span>
                                <span className="btns">
                                    <button type="button" onClick={handleCfgSave} disabled={cfgSaving} className="pa-btn primary"><Save size={14} /> {cfgSaving ? 'Saving…' : 'Save'}</button>
                                    <button type="button" onClick={() => { setCfgDraft({}); setShowSecret({}); }} className="pa-btn">Discard</button>
                                </span>
                            </>
                        )}
                        {cfgMsg && nDirty === 0 && <span className={`pa-flash ${cfgMsg.type}`}>{cfgMsg.text}</span>}
                        {cfgWarnings.length > 0 && <div className="full"><Warnings items={cfgWarnings} /></div>}
                    </div>
                </div>
            )}
        </div>
    );
}

// `icon` is an element, e.g. <Layers size={18} />
function Card({ icon, title, children, right }) {
    return (
        <section className="pa-section">
            <div className="pa-section-head">
                <h2>{icon} {title}</h2>
                {right}
            </div>
            {children}
        </section>
    );
}

function Grid({ children }) {
    return <div className="pa-fields">{children}</div>;
}

function Chip({ ok, children }) {
    return <span className={`pa-dot ${ok ? 'ok' : 'bad'}`}>{children}</span>;
}

function SourceBadge({ field }) {
    // Only the case that changes behaviour is shown: a process env var overrides the env file.
    if (field.source !== 'env') return null;
    return <span className="chip q" title={`Overridden by process environment variable ${field.env_var}`}>env var</span>;
}

function Warnings({ items }) {
    return (
        <div className="pa-warnings">
            {items.map((w, i) => (
                <div key={i}><AlertTriangle size={14} /><span>{w}</span></div>
            ))}
        </div>
    );
}

function ConfigField({ field, draftValue, onChange, onRevert, showSecret, toggleSecret }) {
    const dirty = draftValue !== undefined;
    const disabled = !field.editable;
    const base = `pa-input ${dirty ? 'dirty' : ''}`;
    const current = field.value;
    let input;
    if (field.type === 'secret') {
        input = (
            <div className="pa-secret">
                <input type={showSecret ? 'text' : 'password'} value={draftValue ?? ''} disabled={disabled} autoComplete="new-password"
                    onChange={e => onChange(e.target.value)}
                    placeholder={field.configured ? `configured (${field.hint}) — type to replace` : 'not configured — type to set'}
                    className={`${base} mono`} />
                <button type="button" onClick={toggleSecret} title={showSecret ? 'Hide' : 'Show typed value'}>{showSecret ? <EyeOff size={14} /> : <Eye size={14} />}</button>
            </div>
        );
    } else if (field.type === 'bool') {
        const val = dirty ? draftValue : !!current;
        input = (
            <label className={`pa-check ${disabled ? 'off' : ''}`}>
                <input type="checkbox" checked={!!val} disabled={disabled} onChange={e => onChange(e.target.checked)} />
                <span>{val ? 'enabled' : 'disabled'}</span>
            </label>
        );
    } else if (field.type === 'enum') {
        input = (
            <select value={dirty ? draftValue : (current ?? '')} disabled={disabled} onChange={e => onChange(e.target.value)} className={base}>
                {(field.options || []).map((o, i) => <option key={o} value={o}>{field.optionLabels?.[i] ?? o}</option>)}
            </select>
        );
    } else if (field.type === 'int') {
        input = <input type="number" min={field.min ?? undefined} max={field.max ?? undefined} value={dirty ? draftValue : (current ?? '')} disabled={disabled} onChange={e => onChange(e.target.value)} className={`${base} num`} />;
    } else if (field.type === 'list') {
        input = <input type="text" value={dirty ? draftValue : (Array.isArray(current) ? current.join(', ') : (current ?? ''))} disabled={disabled} onChange={e => onChange(e.target.value)} className={`${base} mono`} />;
    } else if (field.type === 'text') {
        input = <textarea value={dirty ? draftValue : (current ?? '')} disabled={disabled} onChange={e => onChange(e.target.value)} className={`${base} mono`} />;
    } else {
        input = <input type="text" value={dirty ? draftValue : (current ?? '')} disabled={disabled} onChange={e => onChange(e.target.value)} className={`${base} mono`} />;
    }
    return (
        <div className={`pa-field ${field.type === 'text' ? 'wide' : ''}`}>
            <div className="lbl">
                <label title={field.key}>
                    <span>{field.label}</span><SourceBadge field={field} />
                </label>
                {dirty && <button type="button" onClick={onRevert} className="revert">revert</button>}
            </div>
            {field.description && <p className="desc">{field.description}</p>}
            {input}
            {field.source === 'env' && field.editable && <p className="desc warn">Overridden by environment variable <code>{field.env_var}</code> — saving here has no effect until it is removed from the container environment.</p>}
        </div>
    );
}

function Stat({ label, value, sub, accent }) {
    return (
        <div className="pa-stat">
            <div className="k">{label}</div>
            <div className={`v ${accent ? 'accent' : ''}`}>{value}</div>
            {sub && <div className="s">{sub}</div>}
        </div>
    );
}

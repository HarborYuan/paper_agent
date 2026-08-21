import React from 'react';
import { Filter, Microscope, ArrowRight, Sparkles, ThumbsUp, ThumbsDown, Flag, User } from 'lucide-react';

/**
 * Renders the scoring details stored in paper.score_reason.
 * Supports:
 *   - new two-stage JSON: {"stage1": {...}, "stage2": {...}, "boost": {...}, "final": n}
 *   - legacy single-stage JSON: {"score", "relevance", "novelty", "clarity", "risk_flags", "one_line_reason"}
 *   - plain strings (e.g. "User assigned score")
 */
function parseScoreReason(raw) {
    if (!raw) return null;
    if (typeof raw === 'object') return { kind: 'two_stage', data: raw };
    let data = null;
    try { data = JSON.parse(raw); } catch { return { kind: 'text', text: raw }; }
    if (data && typeof data === 'object') {
        if (data.stage1 || data.stage2) return { kind: 'two_stage', data };
        if ('score' in data) return { kind: 'legacy', data };
    }
    return { kind: 'text', text: raw };
}

const DIM_LABELS = { relevance: 'Relevance', novelty: 'Novelty', quality: 'Quality', clarity: 'Clarity' };

function Dim({ name, value }) {
    const v = Number(value);
    const pct = Number.isFinite(v) ? Math.max(0, Math.min(5, v)) / 5 * 100 : 0;
    return (
        <div className="min-w-[90px]">
            <div className="flex justify-between text-[10px] uppercase tracking-wider text-slate-500 mb-1">
                <span>{DIM_LABELS[name] || name}</span><span className="font-mono text-slate-300">{Number.isFinite(v) ? v : '—'}/5</span>
            </div>
            <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div className="h-full bg-cyan-500/70 rounded-full" style={{ width: `${pct}%` }} />
            </div>
        </div>
    );
}

function Flags({ flags }) {
    if (!flags || !flags.length) return null;
    return (
        <div className="flex flex-wrap gap-1.5 mt-2">
            {flags.map((f, i) => (
                <span key={i} className="flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-red-500/10 text-red-300 border border-red-500/20"><Flag size={9} />{f}</span>
            ))}
        </div>
    );
}

function StageCard({ icon: Icon, title, stage, dims, accent }) {
    if (!stage) return null;
    const scoreCls = accent ? 'text-cyan-300' : 'text-slate-200';
    return (
        <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4">
            <div className="flex items-start justify-between gap-3 mb-3">
                <div className="flex items-center gap-2 text-sm font-bold text-slate-300"><Icon size={15} className="text-slate-500" /> {title}</div>
                <div className="text-right">
                    {stage.error ? (
                        <span className="text-xs text-red-400">{stage.error}</span>
                    ) : (
                        <span className={`text-2xl font-black font-mono ${scoreCls}`}>{stage.score ?? '—'}</span>
                    )}
                    {stage.model && <div className="text-[10px] font-mono text-slate-500">{stage.model}</div>}
                </div>
            </div>
            {!stage.error && (
                <>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                        {dims.filter(d => stage[d] !== undefined).map(d => <Dim key={d} name={d} value={stage[d]} />)}
                    </div>
                    {stage.one_line_reason && <p className="text-sm text-slate-300 leading-relaxed">{stage.one_line_reason}</p>}
                    {(stage.strengths?.length || stage.weaknesses?.length) ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                            {stage.strengths?.length ? (
                                <ul className="space-y-1">
                                    {stage.strengths.map((s, i) => <li key={i} className="flex items-start gap-1.5 text-xs text-green-300/90"><ThumbsUp size={11} className="mt-0.5 shrink-0" />{s}</li>)}
                                </ul>
                            ) : <div />}
                            {stage.weaknesses?.length ? (
                                <ul className="space-y-1">
                                    {stage.weaknesses.map((s, i) => <li key={i} className="flex items-start gap-1.5 text-xs text-orange-300/90"><ThumbsDown size={11} className="mt-0.5 shrink-0" />{s}</li>)}
                                </ul>
                            ) : null}
                        </div>
                    ) : null}
                    <Flags flags={stage.risk_flags} />
                    {stage.had_full_text === false && <p className="text-[11px] text-yellow-400/80 mt-2">Reviewed from the abstract only (PDF text unavailable).</p>}
                </>
            )}
        </div>
    );
}

export default function ScoreBreakdown({ scoreReason, userScore }) {
    const parsed = parseScoreReason(scoreReason);
    if (!parsed) return null;

    if (parsed.kind === 'text') {
        return (
            <p className="text-sm text-slate-400 font-mono bg-slate-950 p-4 rounded-lg overflow-x-auto flex items-center gap-2">
                {userScore !== null && userScore !== undefined && <User size={14} className="text-yellow-400" />}{parsed.text}
            </p>
        );
    }

    if (parsed.kind === 'legacy') {
        return <StageCard icon={Filter} title="AI scoring" stage={parsed.data} dims={['relevance', 'novelty', 'clarity']} accent />;
    }

    const { stage1, stage2, boost, final } = parsed.data;
    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs text-slate-500">
                <span>Stage 1 {stage1?.score ?? '—'}</span>
                <ArrowRight size={12} />
                <span>{stage2 ? (stage2.error ? 'Stage 2 failed' : `Stage 2 ${stage2.score}`) : 'below stage-2 threshold · no review'}</span>
                {boost && (<><ArrowRight size={12} /><span className="flex items-center gap-1 text-yellow-300"><Sparkles size={11} /> boosted to {boost.to} ({boost.reason})</span></>)}
                {final !== undefined && (<><ArrowRight size={12} /><span className="text-slate-300 font-bold">final {final}</span></>)}
            </div>
            <StageCard icon={Filter} title="Stage 1 · Screening" stage={stage1} dims={['relevance', 'novelty', 'clarity']} accent={!stage2 || stage2.error} />
            <StageCard icon={Microscope} title="Stage 2 · Review" stage={stage2} dims={['relevance', 'novelty', 'quality', 'clarity']} accent />
        </div>
    );
}

import React from 'react';
import { Filter, Microscope, ArrowRight, Sparkles, Flag, User, BookOpen } from 'lucide-react';
import { VERDICT_LABEL, parseScoreReason } from '../lib/papers';

// Scoring details from paper.score_reason, in the `.pa` look (home.css); formats are listed at parseScoreReason.
const DIM_LABELS = { relevance: 'Relevance', novelty: 'Novelty', quality: 'Quality', clarity: 'Clarity', evidence: 'Evidence', reusability: 'Reusability' };

function Dim({ name, value }) {
    const v = Number(value);
    const pct = Number.isFinite(v) ? Math.max(0, Math.min(5, v)) / 5 * 100 : 0;
    return (
        <div className="pa-dim">
            <div className="lbl"><span>{DIM_LABELS[name] || name}</span><b>{Number.isFinite(v) ? v : '—'}/5</b></div>
            <div className="bar"><span style={{ width: `${pct}%` }} /></div>
        </div>
    );
}

function StageCard({ icon, title, stage, dims, accent }) {
    if (!stage) return null;
    return (
        <div className={`pa-stage ${accent ? 'final' : ''}`}>
            <div className="hd">
                <span className="t">{icon} {title}</span>
                {stage.verdict && <span className={`pill ${stage.verdict}`}>{VERDICT_LABEL[stage.verdict] || stage.verdict}</span>}
                <span className="sc">
                    {stage.error ? <span className="err">{stage.error}</span> : <b>{stage.score ?? '—'}</b>}
                    {stage.model && <small>{stage.model}</small>}
                </span>
            </div>
            {!stage.error && (
                <>
                    <div className="dims">
                        {dims.filter(d => stage[d] !== undefined).map(d => <Dim key={d} name={d} value={stage[d]} />)}
                    </div>
                    {stage.one_line_reason && <p className="why">{stage.one_line_reason}</p>}
                    {stage.risk_flags?.length > 0 && (
                        <div className="flags">
                            {stage.risk_flags.map((f, i) => <span key={i} className="chip q"><Flag size={10} /> {f}</span>)}
                        </div>
                    )}
                    {stage.deep_read === true && (
                        <p className="note"><BookOpen size={12} />
                            <span>Deep read: the reviewer requested the extended text{stage.deep_read_reason ? ` — ${stage.deep_read_reason}` : ''}</span>
                        </p>
                    )}
                    {stage.had_full_text === false && <p className="note warn">Reviewed from the abstract only (PDF text unavailable).</p>}
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
            <p className="pa-scoretext">
                {userScore !== null && userScore !== undefined && <User size={14} />}{parsed.text}
            </p>
        );
    }

    if (parsed.kind === 'legacy') {
        return <StageCard icon={<Filter size={14} />} title="AI scoring" stage={parsed.data} dims={['relevance', 'novelty', 'clarity']} accent />;
    }

    const { stage1, stage2, deep, boost, final, pipeline } = parsed.data;
    const boosted = boost && <span className="pa-boost"><Sparkles size={12} /> boosted to {boost.to} ({boost.reason})</span>;
    if (pipeline === 'verdict') {
        return (
            <div className="pa-stages">
                <StageCard icon={<Filter size={14} />} title="① Screen" stage={stage1} dims={['relevance']} accent={!stage2} />
                <StageCard icon={<Microscope size={14} />} title="② Review" stage={stage2} dims={['relevance', 'novelty', 'evidence', 'reusability']} accent={!deep} />
                <StageCard icon={<BookOpen size={14} />} title="③ Deep read" stage={deep} dims={['relevance', 'novelty', 'evidence', 'reusability']} accent />
                {boosted}
            </div>
        );
    }
    return (
        <div className="pa-stages">
            <div className="pa-flow">
                <span>Stage 1 {stage1?.score ?? '—'}</span>
                <ArrowRight size={12} />
                <span>{stage2 ? (stage2.error ? 'Stage 2 failed' : `Stage 2 ${stage2.score}`) : 'below stage-2 threshold · no review'}</span>
                {boost && <><ArrowRight size={12} />{boosted}</>}
                {final !== undefined && <><ArrowRight size={12} /><b>final {final}</b></>}
            </div>
            <StageCard icon={<Filter size={14} />} title="Stage 1 · Screening" stage={stage1} dims={['relevance', 'novelty', 'clarity']} accent={!stage2 || stage2.error} />
            <StageCard icon={<Microscope size={14} />} title="Stage 2 · Review" stage={stage2} dims={['relevance', 'novelty', 'quality', 'clarity']} accent />
        </div>
    );
}

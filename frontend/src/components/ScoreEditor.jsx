import React, { useState } from 'react';
import axios from 'axios';
import { Check, X } from 'lucide-react';

const API_URL = '/api';

// The "★ 92" score chip of the `.pa` pages; click to set a user score (0-100).
// `onSaved(score)` runs after the PATCH succeeds.
const ScoreEditor = ({ paper, onSaved }) => {
    const [score, setScore] = useState(paper.user_score ?? paper.score);
    const [userSet, setUserSet] = useState(paper.user_score != null);
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(score ?? 0);

    const save = async (e) => {
        e.stopPropagation();
        const val = parseInt(draft, 10);
        if (isNaN(val) || val < 0 || val > 100) { alert('Score must be 0-100'); return; }
        try {
            await axios.patch(`${API_URL}/papers/${paper.id}/score`, null, { params: { score: val } });
            setScore(val);
            setUserSet(true);
            setEditing(false);
            onSaved?.(val);
        } catch (err) {
            console.error('Failed to update score', err);
            alert('Failed to update score');
        }
    };

    if (editing) {
        return (
            <span className="pa-score-edit" onClick={e => e.stopPropagation()}>
                <input type="number" min="0" max="100" value={draft} autoFocus aria-label="Score (0-100)"
                    onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') save(e); if (e.key === 'Escape') setEditing(false); }} />
                <button type="button" onClick={save} title="Save"><Check size={13} /></button>
                <button type="button" onClick={e => { e.stopPropagation(); setEditing(false); }} title="Cancel"><X size={13} /></button>
            </span>
        );
    }
    const title = userSet
        ? 'User score · click to edit'
        : `${paper.score_stage1 != null ? `Screen ${paper.score_stage1 / 20}/5 → ` : ''}final ${paper.score ?? '–'}${paper.score_model ? ` (${paper.score_model})` : ''} · click to edit`;
    return (
        <button type="button" className={`pa-score ${score == null ? '' : score >= 85 ? 'hi' : 'lo'}`} title={title}
            onClick={e => { e.stopPropagation(); setDraft(score ?? 0); setEditing(true); }}>
            {score == null ? 'Set score' : `★ ${score}`}
        </button>
    );
};

export default ScoreEditor;

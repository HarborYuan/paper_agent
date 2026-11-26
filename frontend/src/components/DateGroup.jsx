import React from 'react';
import { RefreshCw } from 'lucide-react';

const DateGroup = ({ dateLabel, count, total, minScore, onReRank }) => (
    <div className="pa-day">
        <h2>{dateLabel}</h2>
        <small>
            {minScore > 0 ? `${count} ${count === 1 ? 'paper' : 'papers'} ≥ ${minScore} · ${total} that day` : `${total} papers`}
        </small>
        {onReRank && (
            <button type="button" onClick={onReRank} title="Re-score papers for this date"><RefreshCw size={14} /></button>
        )}
        <span className="rule" />
    </div>
);

export default DateGroup;

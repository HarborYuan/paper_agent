import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import Masonry from 'react-masonry-css';
import { format, isToday, isYesterday } from 'date-fns';
import { useInView } from 'react-intersection-observer';
import { RefreshCw } from 'lucide-react';
import DateGroup from './DateGroup';
import DigestCard from './DigestCard';
import { COLUMNS } from '../lib/papers';

const API_URL = '/api';

const dayLabel = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    const date = new Date(y, m - 1, d);
    if (isToday(date)) return 'Today';
    if (isYesterday(date)) return 'Yesterday';
    return format(date, 'MMMM d, yyyy');
};

// The home page digest: one publication day per request from /api/papers/feed, every paper of that
// day scoring >= minScore, the next day loaded as the bottom of the page comes into view.
// Remount it (change its key) to start over, e.g. when the score filter changes.
const Feed = ({ minScore }) => {
    const [groups, setGroups] = useState([]);          // [{ date: 'YYYY-MM-DD', total, papers }]
    const [cursor, setCursor] = useState(undefined);   // undefined: latest day · 'YYYY-MM-DD': next day · null: end
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const busy = useRef(false);
    const { ref: sentinel, inView } = useInView({ rootMargin: '800px' });

    const loadMore = useCallback(async () => {
        if (busy.current || cursor === null) return;
        busy.current = true;
        setLoading(true);
        try {
            const params = { min_score: minScore };
            if (cursor) params.before = cursor;
            const { data } = await axios.get(`${API_URL}/papers/feed`, { params });
            if (data.date) {
                setGroups(prev => prev.some(g => g.date === data.date) ? prev : [...prev, data]);
            }
            setCursor(data.date ? (data.next ?? null) : null);
        } catch (err) {
            console.error('Failed to fetch papers', err);
            setError(err.response?.data?.detail || err.message);
        } finally {
            busy.current = false;
            setLoading(false);
        }
    }, [cursor, minScore]);

    useEffect(() => {
        if (!loading && !error && cursor !== null && (cursor === undefined || inView)) loadMore();
    }, [inView, loading, error, cursor, loadMore]);

    const reScore = async (date) => {
        if (!window.confirm(`Are you sure you want to re-score all papers from ${date}?`)) return;
        try {
            await axios.post(`${API_URL}/papers/re-score-date`, null, { params: { date } });
            alert(`Re-scoring started for ${date}. Please refresh in a few moments.`);
        } catch (err) {
            console.error('Failed to re-score date', err);
            alert(err.response?.data?.detail || 'Failed to trigger re-scoring.');
        }
    };

    return (
        <>
            {groups.map(g => (
                <section key={g.date}>
                    <DateGroup dateLabel={dayLabel(g.date)} count={g.papers.length} total={g.total}
                        minScore={minScore} onReRank={() => reScore(g.date)} />
                    <Masonry breakpointCols={COLUMNS} className="pa-grid" columnClassName="pa-col">
                        {g.papers.map(p => <DigestCard key={p.id} paper={p} />)}
                    </Masonry>
                </section>
            ))}

            <div ref={sentinel} className="pa-sentinel">
                {loading && <RefreshCw className="animate-spin" size={22} />}
                {error && (
                    <span>Could not load papers ({error}). <button type="button" className="pa-btn" onClick={() => setError(null)}>Retry</button></span>
                )}
                {!loading && !error && cursor === null && groups.length > 0 && <span>That's every day with papers ≥ {minScore}.</span>}
            </div>

            {!loading && !error && cursor === null && groups.length === 0 && (
                <div className="pa-empty">
                    <h3>No papers{minScore > 0 ? ` with a score ≥ ${minScore}` : ''}</h3>
                    <p>{minScore > 0 ? 'Lower the score filter, or trigger a fetch.' : 'Trigger a fetch to get started.'}</p>
                </div>
            )}
        </>
    );
};

export default Feed;

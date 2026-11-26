// Small helpers shared by the paper components.

// Authors arrive as an array (light card records) or as the JSON string stored on the paper.
export const parseAuthors = (authors) => {
    if (Array.isArray(authors)) return authors;
    if (typeof authors !== 'string' || !authors.trim()) return [];
    try {
        const v = JSON.parse(authors);
        return Array.isArray(v) ? v : [];
    } catch {
        return authors.replace(/[[\]']/g, '').split(',').map(s => s.trim().replace(/"/g, '')).filter(Boolean);
    }
};

// The app route of an author's page; AuthorDetail reads the decoded :name param.
export const authorPath = (name) => `/author/${encodeURIComponent(name)}`;

// Masonry columns of the home page cards.
export const COLUMNS = { default: 2, 900: 1 };

// Display names of the verdicts (CSS classes of the same names colour the `.pill`).
export const VERDICT_LABEL = { must_read: 'Must Read', worth_reading: 'Worth Reading', skim: 'Skim', skip: 'Skip' };

/**
 * Parses paper.score_reason. Supports:
 *   - verdict pipeline JSON: {"pipeline": "verdict", "stage1", "stage2", "deep", "boost"}
 *   - older two-stage JSON: {"stage1": {...}, "stage2": {...}, "boost": {...}, "final": n}
 *   - legacy single-stage JSON: {"score", "relevance", "novelty", "clarity", "risk_flags", "one_line_reason"}
 *   - plain strings (e.g. "User assigned score")
 */
export function parseScoreReason(raw) {
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

// Final verdict: the deep read's if any, else the review's (same rule as paper_verdict on the server).
export function finalVerdict(raw) {
    const p = parseScoreReason(raw);
    if (!p || p.kind !== 'two_stage') return null;
    const fin = p.data.deep || p.data.stage2 || {};
    return fin.verdict || null;
}

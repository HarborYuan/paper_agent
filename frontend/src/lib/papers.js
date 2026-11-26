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

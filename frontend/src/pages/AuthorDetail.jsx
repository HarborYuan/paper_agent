import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import Masonry from 'react-masonry-css';
import { ChevronLeft, Search, Edit2, Globe, Building, Star, Save, RefreshCw } from 'lucide-react';
import TopBar from '../components/TopBar';
import DigestCard from '../components/DigestCard';
import { COLUMNS } from '../lib/papers';

const API_URL = '/api'; // All backend endpoints live under /api (same origin)

const TIME_RANGES = [
    { label: '7d', value: 7 },
    { label: '30d', value: 30 },
    { label: '90d', value: 90 },
    { label: '180d', value: 180 },
    { label: '360d', value: 360 },
    { label: 'All', value: null },
];

const EMPTY_DETAILS = { bio: '', website: '', affiliation: '', is_important: false };

const toDetails = (data) => ({
    bio: data.bio || '',
    website: data.website || '',
    affiliation: data.affiliation || '',
    is_important: data.is_important || false,
});

const AuthorDetail = () => {
    const { name } = useParams();
    const navigate = useNavigate();
    const [papers, setPapers] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [loadError, setLoadError] = useState(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedDays, setSelectedDays] = useState(7);

    const [authorDetails, setAuthorDetails] = useState(EMPTY_DETAILS);
    const [isEditing, setIsEditing] = useState(false);
    const [editForm, setEditForm] = useState(EMPTY_DETAILS);
    const [isSaving, setIsSaving] = useState(false);

    // Light card records (no full text); a stale response from an earlier range is dropped.
    useEffect(() => {
        let stale = false;
        setIsLoading(true);
        setLoadError(null);
        const params = { view: 'card', ...(selectedDays !== null ? { days: selectedDays } : {}) };
        axios.get(`${API_URL}/authors/${encodeURIComponent(name)}/papers`, { params })
            .then(res => { if (!stale) setPapers(res.data); })
            .catch(error => {
                console.error('Failed to fetch papers for author', error);
                if (!stale) { setPapers([]); setLoadError(error.message); }
            })
            .finally(() => { if (!stale) setIsLoading(false); });
        return () => { stale = true; };
    }, [name, selectedDays]);

    useEffect(() => {
        let stale = false;
        setIsEditing(false);
        axios.get(`${API_URL}/authors/${encodeURIComponent(name)}/details`)
            .then(res => {
                if (stale) return;
                const details = toDetails(res.data);
                setAuthorDetails(details);
                setEditForm(details);
            })
            .catch(error => console.error('Failed to fetch author details', error));
        return () => { stale = true; };
    }, [name]);

    const handleSaveAuthor = async () => {
        setIsSaving(true);
        try {
            const res = await axios.patch(`${API_URL}/authors/${encodeURIComponent(name)}`, editForm);
            const details = toDetails(res.data);
            setAuthorDetails(details);
            setEditForm(details);
            setIsEditing(false);
        } catch (error) {
            console.error('Failed to save author details', error);
            alert('Failed to save changes.');
        } finally {
            setIsSaving(false);
        }
    };

    // Quick toggle next to the name, applied optimistically and reverted if the save fails.
    const toggleImportant = async () => {
        const previousValue = authorDetails.is_important;
        const newValue = !previousValue;
        setAuthorDetails(prev => ({ ...prev, is_important: newValue }));
        setEditForm(prev => ({ ...prev, is_important: newValue }));
        try {
            await axios.patch(`${API_URL}/authors/${encodeURIComponent(name)}`, { is_important: newValue });
        } catch (error) {
            console.error('Failed to update importance', error);
            setAuthorDetails(prev => ({ ...prev, is_important: previousValue }));
            setEditForm(prev => ({ ...prev, is_important: previousValue }));
        }
    };

    // Back to wherever the author link was clicked; a page opened directly (new tab, typed URL) goes to the digest.
    // React Router keeps its own entry index in history.state; window.history.length also counts other sites.
    const goBack = () => {
        if ((window.history.state?.idx ?? 0) > 0) navigate(-1);
        else navigate('/');
    };

    const q = searchQuery.trim().toLowerCase();
    const filteredPapers = q
        ? papers.filter(p => [p.title, p.tldr, p.abstract].some(t => t && t.toLowerCase().includes(q)))
        : papers;
    const rangeLabel = selectedDays === null ? 'in total' : `in the last ${selectedDays} days`;

    return (
        <div className="pa">
            <TopBar />

            <main className="pa-main">
                <section className="pa-hero">
                    <div className="pa-kicker">
                        <button type="button" className="pa-back" onClick={goBack}><ChevronLeft size={14} />Back</button>
                    </div>
                    <div className="pa-author-head">
                        <h1>{name}</h1>
                        <button type="button" onClick={toggleImportant}
                            className={`pa-btn small ${authorDetails.is_important ? 'starred' : ''}`}
                            title={authorDetails.is_important ? 'Click to unmark' : 'Mark as an important author'}>
                            <Star size={13} className={authorDetails.is_important ? 'fill' : ''} />
                            {authorDetails.is_important ? 'Important Author' : 'Claim as Important'}
                        </button>
                        {!isEditing && (
                            <button type="button" onClick={() => setIsEditing(true)} className="pa-btn small" title="Edit Profile">
                                <Edit2 size={13} /> Edit
                            </button>
                        )}
                    </div>

                    {isEditing ? (
                        <div className="pa-form">
                            <label>
                                <span>Affiliation</span>
                                <div className="field">
                                    <Building className="icon" size={15} />
                                    <input type="text" value={editForm.affiliation} placeholder="University or Company"
                                        onChange={(e) => setEditForm({ ...editForm, affiliation: e.target.value })} />
                                </div>
                            </label>
                            <label>
                                <span>Website</span>
                                <div className="field">
                                    <Globe className="icon" size={15} />
                                    <input type="text" value={editForm.website} placeholder="https://..."
                                        onChange={(e) => setEditForm({ ...editForm, website: e.target.value })} />
                                </div>
                            </label>
                            <label>
                                <span>Bio</span>
                                <textarea value={editForm.bio} placeholder="Short biography..."
                                    onChange={(e) => setEditForm({ ...editForm, bio: e.target.value })} />
                            </label>
                            <div className="actions">
                                <button type="button" className="pa-btn"
                                    onClick={() => { setIsEditing(false); setEditForm(authorDetails); }}>
                                    Cancel
                                </button>
                                <button type="button" className="pa-btn primary" onClick={handleSaveAuthor} disabled={isSaving}>
                                    <Save size={14} /> {isSaving ? 'Saving…' : 'Save Profile'}
                                </button>
                            </div>
                        </div>
                    ) : (
                        <div className="pa-author-info">
                            {(authorDetails.affiliation || authorDetails.website) && (
                                <div className="pa-author-links">
                                    {authorDetails.affiliation && (
                                        <span><Building size={14} />{authorDetails.affiliation}</span>
                                    )}
                                    {authorDetails.website && (
                                        <a href={authorDetails.website} target="_blank" rel="noopener noreferrer">
                                            <Globe size={14} />{authorDetails.website.replace(/^https?:\/\//, '')}
                                        </a>
                                    )}
                                </div>
                            )}
                            {authorDetails.bio && <p className="pa-bio">{authorDetails.bio}</p>}
                        </div>
                    )}

                    <div className="pa-controls">
                        <div className="pa-tabs" role="group" aria-label="Time range">
                            {TIME_RANGES.map(range => (
                                <button key={range.label} type="button" onClick={() => setSelectedDays(range.value)}
                                    className={selectedDays === range.value ? 'on' : ''}>
                                    {range.label}
                                </button>
                            ))}
                        </div>
                        <span className="pa-meta">
                            <b>{isLoading ? '…' : papers.length}</b> {papers.length === 1 ? 'paper' : 'papers'} {rangeLabel}
                        </span>
                    </div>
                    <div className="pa-search plain">
                        <Search className="icon" size={17} />
                        <input type="text" placeholder="Search in this author's papers (title, TL;DR, abstract)…"
                            value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
                    </div>
                </section>

                {isLoading ? (
                    <div className="pa-sentinel"><RefreshCw className="animate-spin" size={22} /></div>
                ) : loadError ? (
                    <div className="pa-empty">
                        <h3>Could not load papers</h3>
                        <p>{loadError}</p>
                    </div>
                ) : filteredPapers.length > 0 ? (
                    <>
                        {q && (
                            <div className="pa-day">
                                <h2>Search results</h2>
                                <small>{filteredPapers.length} of {papers.length} papers</small>
                                <span className="rule" />
                            </div>
                        )}
                        <Masonry breakpointCols={COLUMNS} className="pa-grid" columnClassName="pa-col">
                            {filteredPapers.map(paper => <DigestCard key={paper.id} paper={paper} />)}
                        </Masonry>
                    </>
                ) : (
                    <div className="pa-empty">
                        {q ? (
                            <><h3>No papers matched your search</h3><p>Try a different keyword.</p></>
                        ) : (
                            <><h3>No papers {rangeLabel}</h3><p>Try a longer time range.</p></>
                        )}
                    </div>
                )}
            </main>
        </div>
    );
};

export default AuthorDetail;

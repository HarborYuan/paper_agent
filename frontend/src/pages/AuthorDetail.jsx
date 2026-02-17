import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';
import Masonry from 'react-masonry-css';
import { ChevronRight, Users, BookOpen, Search, Calendar, Edit2, Check, X, Globe, Building, Star, Save } from 'lucide-react';
import PaperCard from '../components/PaperCard';

const API_URL = '';

const TIME_RANGES = [
    { label: '7d', value: 7 },
    { label: '30d', value: 30 },
    { label: '90d', value: 90 },
    { label: '180d', value: 180 },
    { label: '360d', value: 360 },
    { label: 'All', value: null },
];

const AuthorDetail = () => {
    const { name } = useParams();
    const [papers, setPapers] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedDays, setSelectedDays] = useState(7);

    // Author Metadata State
    const [authorDetails, setAuthorDetails] = useState({
        bio: '',
        website: '',
        affiliation: '',
        is_important: false
    });
    const [isEditing, setIsEditing] = useState(false);
    const [editForm, setEditForm] = useState({
        bio: '',
        website: '',
        affiliation: '',
        is_important: false
    });
    const [isSaving, setIsSaving] = useState(false);

    useEffect(() => {
        const fetchPapers = async () => {
            setIsLoading(true);
            try {
                const params = selectedDays !== null ? { days: selectedDays } : {};
                const res = await axios.get(`${API_URL}/authors/${encodeURIComponent(name)}/papers`, { params });
                setPapers(res.data);
            } catch (error) {
                console.error("Failed to fetch papers for author", error);
            } finally {
                setIsLoading(false);
            }
        };

        const fetchAuthorDetails = async () => {
            try {
                const res = await axios.get(`${API_URL}/authors/${encodeURIComponent(name)}/details`);
                const data = res.data;
                // Ensure default values if null
                const details = {
                    bio: data.bio || '',
                    website: data.website || '',
                    affiliation: data.affiliation || '',
                    is_important: data.is_important || false
                };
                setAuthorDetails(details);
                setEditForm(details);
            } catch (error) {
                console.error("Failed to fetch author details", error);
            }
        };

        fetchPapers();
        fetchAuthorDetails();
    }, [name, selectedDays]);

    const handleSaveAuthor = async () => {
        setIsSaving(true);
        try {
            const res = await axios.patch(`${API_URL}/authors/${encodeURIComponent(name)}`, editForm);
            const data = res.data;
            const details = {
                bio: data.bio || '',
                website: data.website || '',
                affiliation: data.affiliation || '',
                is_important: data.is_important || false
            };
            setAuthorDetails(details);
            setIsEditing(false);
        } catch (error) {
            console.error("Failed to save author details", error);
            alert("Failed to save changes.");
        } finally {
            setIsSaving(false);
        }
    };

    const toggleImportant = async () => {
        // Optimistic update for the checkbox outside of edit mode? 
        // Or strictly use edit mode? User request says "add a check box to claim".
        // Let's allow direct toggle if not editing, or part of edit form?
        // Let's make it part of the edit form for consistency, OR a quick toggle.
        // User request: "Also, add a checkbox to claim the important author."
        // Let's implement it as a quick toggle button near the name.

        const newValue = !authorDetails.is_important;
        const previousValue = authorDetails.is_important;

        setAuthorDetails(prev => ({ ...prev, is_important: newValue }));
        setEditForm(prev => ({ ...prev, is_important: newValue })); // Keep form in sync

        try {
            await axios.patch(`${API_URL}/authors/${encodeURIComponent(name)}`, {
                is_important: newValue
            });
        } catch (error) {
            console.error("Failed to update importance", error);
            // Revert
            setAuthorDetails(prev => ({ ...prev, is_important: previousValue }));
            setEditForm(prev => ({ ...prev, is_important: previousValue }));
        }
    };


    const filteredPapers = papers.filter(paper =>
        paper.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (paper.summary_personalized && paper.summary_personalized.toLowerCase().includes(searchQuery.toLowerCase()))
    );

    const masonryBreakpoints = {
        default: 3,
        1100: 2,
        700: 1
    };

    return (
        <div className="min-h-screen bg-[#0f172a] text-slate-200 p-6 md:p-12 font-sans">
            <header className="max-w-7xl mx-auto mb-12">
                <Link to="/authors" className="text-cyan-400 hover:text-cyan-300 mb-6 inline-block font-medium flex items-center gap-2">
                    <ChevronRight size={16} className="rotate-180" />
                    Back to Authors
                </Link>

                <div className="flex flex-col md:flex-row md:items-start justify-between gap-6 pb-8 border-b border-slate-700/50">
                    <div className="flex items-start gap-6 flex-1">
                        <div className="w-16 h-16 md:w-24 md:h-24 rounded-2xl bg-gradient-to-br from-cyan-500 to-blue-600 flex-shrink-0 flex items-center justify-center text-slate-900 shadow-lg shadow-cyan-500/20">
                            {authorDetails.is_important ? <Star size={48} className="text-yellow-300 fill-yellow-300" /> : <Users size={40} />}
                        </div>

                        <div className="flex-1 w-full">
                            <div className="flex items-center gap-4 mb-2 flex-wrap">
                                <h1 className="text-3xl md:text-4xl font-black text-white">
                                    {name}
                                </h1>

                                <button
                                    onClick={toggleImportant}
                                    className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider transition-all flex items-center gap-1.5 ${authorDetails.is_important
                                            ? 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/50 hover:bg-yellow-500/30'
                                            : 'bg-slate-700/50 text-slate-400 border border-slate-600 hover:bg-slate-700'
                                        }`}
                                >
                                    <Star size={12} className={authorDetails.is_important ? "fill-current" : ""} />
                                    {authorDetails.is_important ? "Important Author" : "Claim as Important"}
                                </button>

                                {!isEditing && (
                                    <button
                                        onClick={() => setIsEditing(true)}
                                        className="ml-auto md:ml-4 text-slate-400 hover:text-white transition-colors bg-slate-800/50 p-2 rounded-lg border border-slate-700/50 hover:border-slate-600"
                                        title="Edit Profile"
                                    >
                                        <Edit2 size={16} />
                                    </button>
                                )}
                            </div>

                            {isEditing ? (
                                <div className="bg-slate-800/80 p-6 rounded-xl border border-slate-700/50 backdrop-blur-sm mt-4 max-w-2xl">
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                                        <div className="col-span-2">
                                            <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-1.5">Affiliation</label>
                                            <div className="relative">
                                                <Building className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
                                                <input
                                                    type="text"
                                                    value={editForm.affiliation}
                                                    onChange={(e) => setEditForm({ ...editForm, affiliation: e.target.value })}
                                                    className="w-full bg-slate-900/50 border border-slate-600 rounded-lg pl-10 pr-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500"
                                                    placeholder="University or Company"
                                                />
                                            </div>
                                        </div>
                                        <div className="col-span-2">
                                            <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-1.5">Website</label>
                                            <div className="relative">
                                                <Globe className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
                                                <input
                                                    type="text"
                                                    value={editForm.website}
                                                    onChange={(e) => setEditForm({ ...editForm, website: e.target.value })}
                                                    className="w-full bg-slate-900/50 border border-slate-600 rounded-lg pl-10 pr-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500"
                                                    placeholder="https://..."
                                                />
                                            </div>
                                        </div>
                                        <div className="col-span-2">
                                            <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-1.5">Bio</label>
                                            <textarea
                                                value={editForm.bio}
                                                onChange={(e) => setEditForm({ ...editForm, bio: e.target.value })}
                                                className="w-full bg-slate-900/50 border border-slate-600 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-cyan-500 min-h-[80px]"
                                                placeholder="Short biography..."
                                            />
                                        </div>
                                    </div>
                                    <div className="flex justify-end gap-3">
                                        <button
                                            onClick={() => {
                                                setIsEditing(false);
                                                setEditForm(authorDetails); // Reset
                                            }}
                                            className="px-4 py-2 rounded-lg text-sm font-bold text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors"
                                        >
                                            Cancel
                                        </button>
                                        <button
                                            onClick={handleSaveAuthor}
                                            disabled={isSaving}
                                            className="px-4 py-2 rounded-lg text-sm font-bold bg-cyan-500 hover:bg-cyan-400 text-slate-900 transition-colors flex items-center gap-2"
                                        >
                                            <Save size={16} />
                                            {isSaving ? 'Saving...' : 'Save Profile'}
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <div className="space-y-3 mt-2">
                                    {(authorDetails.affiliation || authorDetails.website) && (
                                        <div className="flex flex-wrap gap-4 text-sm text-slate-300">
                                            {authorDetails.affiliation && (
                                                <div className="flex items-center gap-1.5 bg-slate-800/50 px-3 py-1 rounded-full border border-slate-700/50">
                                                    <Building size={14} className="text-cyan-400" />
                                                    <span>{authorDetails.affiliation}</span>
                                                </div>
                                            )}
                                            {authorDetails.website && (
                                                <a href={authorDetails.website} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 bg-slate-800/50 px-3 py-1 rounded-full border border-slate-700/50 hover:bg-slate-700 hover:text-cyan-400 transition-colors group">
                                                    <Globe size={14} className="text-cyan-400 group-hover:text-cyan-300" />
                                                    <span className="truncate max-w-[200px]">{authorDetails.website.replace(/^https?:\/\//, '')}</span>
                                                </a>
                                            )}
                                        </div>
                                    )}

                                    {authorDetails.bio && (
                                        <p className="text-slate-400 text-sm max-w-3xl leading-relaxed">
                                            {authorDetails.bio}
                                        </p>
                                    )}

                                    <div className="flex items-center gap-4 text-slate-400 pt-2">
                                        <div className="flex items-center gap-1.5 font-medium">
                                            <BookOpen size={16} className="text-cyan-400" />
                                            <span className="text-slate-200 font-bold">{papers.length}</span> Published Papers
                                        </div>
                                    </div>
                                </div>
                            )}

                        </div>
                    </div>

                    <div className="relative w-full md:w-80 flex-shrink-0">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={18} />
                        <input
                            type="text"
                            placeholder="Search in publications..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full bg-slate-800/50 border border-slate-700 rounded-xl pl-10 pr-4 py-2.5 text-white focus:outline-none focus:border-cyan-500 transition-colors"
                        />
                    </div>
                </div>

                {/* Time Range Selector */}
                <div className="flex items-center gap-3 mt-6">
                    <Calendar size={16} className="text-slate-500" />
                    <div className="flex gap-1.5 bg-slate-800/50 border border-slate-700/50 rounded-xl p-1">
                        {TIME_RANGES.map(range => (
                            <button
                                key={range.label}
                                onClick={() => setSelectedDays(range.value)}
                                className={`px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${selectedDays === range.value
                                    ? 'bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-lg shadow-cyan-500/20'
                                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
                                    }`}
                            >
                                {range.label}
                            </button>
                        ))}
                    </div>
                </div>
            </header>

            <main className="max-w-7xl mx-auto">
                {isLoading ? (
                    <div className="flex justify-center py-20">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500"></div>
                    </div>
                ) : (
                    <>
                        {filteredPapers.length > 0 ? (
                            <Masonry
                                breakpointCols={masonryBreakpoints}
                                className="flex -ml-6 w-auto"
                                columnClassName="pl-6 bg-clip-padding space-y-6"
                            >
                                {filteredPapers.map(paper => (
                                    <PaperCard key={paper.id} paper={paper} />
                                ))}
                            </Masonry>
                        ) : (
                            <div className="py-20 text-center bg-slate-800/20 rounded-3xl border border-slate-700 border-dashed">
                                <BookOpen className="mx-auto mb-4 text-slate-600" size={48} />
                                <h3 className="text-xl font-bold text-slate-300">No papers matched your search</h3>
                                <p className="text-slate-500">Try a different keyword.</p>
                            </div>
                        )}
                    </>
                )}
            </main>
        </div>
    );
};

export default AuthorDetail;

import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Calendar, Users, ExternalLink, Star, Building2, Tag, RefreshCw } from 'lucide-react';
import { format } from 'date-fns';
import ReactMarkdown from 'react-markdown';

const API_URL = '';

const PaperDetail = () => {
    const { id } = useParams();
    const navigate = useNavigate();
    const [paper, setPaper] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [refreshing, setRefreshing] = useState(false);

    useEffect(() => {
        const fetchPaper = async () => {
            try {
                const res = await axios.get(`${API_URL}/papers/${id}`);
                setPaper(res.data);
            } catch (err) {
                setError("Failed to load paper details.");
                console.error(err);
            } finally {
                setLoading(false);
            }
        };

        if (id) {
            fetchPaper();
        }
    }, [id]);

    const handleRefresh = async () => {
        if (refreshing) return;
        setRefreshing(true);
        try {
            await axios.post(`${API_URL}/papers/${id}/resummarize`);
            // Poll for completion (check every 3s, up to 120s)
            let attempts = 0;
            const poll = setInterval(async () => {
                attempts++;
                try {
                    const res = await axios.get(`${API_URL}/papers/${id}`);
                    if (res.data.summary_personalized !== paper?.summary_personalized || attempts >= 40) {
                        clearInterval(poll);
                        setPaper(res.data);
                        setRefreshing(false);
                    }
                } catch {
                    clearInterval(poll);
                    setRefreshing(false);
                }
            }, 3000);
        } catch (error) {
            console.error('Failed to re-summarize', error);
            alert(error.response?.data?.detail || 'Failed to trigger re-summarization');
            setRefreshing(false);
        }
    };

    if (loading) {
        return (
            <div className="min-h-screen bg-[#0f172a] text-slate-200 flex items-center justify-center">
                <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-cyan-500"></div>
            </div>
        );
    }

    if (error || !paper) {
        return (
            <div className="min-h-screen bg-[#0f172a] text-slate-200 flex flex-col items-center justify-center gap-4">
                <p className="text-red-400">{error || "Paper not found"}</p>
                <button
                    onClick={() => navigate(-1)}
                    className="px-4 py-2 bg-slate-700 rounded-lg hover:bg-slate-600 transition"
                >
                    Go Back
                </button>
            </div>
        );
    }

    // Parsing logic similar to PaperCard
    let tags = [];
    try {
        tags = JSON.parse(paper.all_categories.replace(/'/g, '"'));
    } catch (e) {
        tags = [paper.category_primary];
    }

    let parsedAuthors = [];
    if (Array.isArray(paper.authors)) {
        parsedAuthors = paper.authors;
    } else if (typeof paper.authors === 'string') {
        try {
            parsedAuthors = JSON.parse(paper.authors.replace(/'/g, '"'));
        } catch (e) {
            let cleaned = paper.authors.replace(/[\[\]']/g, "");
            parsedAuthors = cleaned.split(',').map(s => s.trim().replace(/"/g, ""));
        }
    }

    // Format Date (UTC)
    // Ensure the date string is treated as UTC
    const dateStr = paper.published_at.endsWith('Z') ? paper.published_at : `${paper.published_at}Z`;
    const dateObj = new Date(dateStr);
    const formattedDate = format(
        new Date(dateObj.getUTCFullYear(), dateObj.getUTCMonth(), dateObj.getUTCDate()),
        'MMMM d, yyyy'
    );

    return (
        <div className="min-h-screen bg-[#0f172a] text-slate-200 p-6 md:p-12 font-sans selection:bg-cyan-500/30">
            <div className="max-w-4xl mx-auto">
                <button
                    onClick={() => navigate(-1)}
                    className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors mb-8 group"
                >
                    <ArrowLeft size={20} className="group-hover:-translate-x-1 transition-transform" />
                    Back to List
                </button>

                <article className="bg-slate-800/50 backdrop-blur-md border border-slate-700/50 rounded-2xl p-8 shadow-2xl">
                    {/* Header */}
                    <div className="mb-6">
                        <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
                            <h1 className="text-3xl md:text-4xl font-black text-white leading-tight font-display">
                                {paper.title}
                            </h1>
                            {paper.score && (
                                <div className={`shrink-0 flex items-center gap-2 px-3 py-1.5 rounded-lg text-lg font-bold ${paper.score >= 85 ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
                                    <Star size={18} fill="currentColor" />
                                    {paper.score}
                                </div>
                            )}
                        </div>

                        <div className="flex flex-wrap items-center gap-6 text-slate-400 mb-6 font-medium">
                            <div className="flex items-center gap-2">
                                <Calendar size={16} className="text-cyan-500" />
                                <span>{formattedDate}</span>
                            </div>
                            {paper.pdf_url && (
                                <a
                                    href={paper.pdf_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex items-center gap-2 text-cyan-400 hover:text-cyan-300 hover:underline transition-colors"
                                >
                                    <ExternalLink size={16} />
                                    View PDF
                                </a>
                            )}
                            {paper.main_affiliation && (
                                <div className="flex items-center gap-2">
                                    <Building2 size={16} className="text-purple-400" />
                                    <span>{paper.main_affiliation}</span>
                                </div>
                            )}
                        </div>

                        <div className="flex flex-wrap gap-2 mb-8">
                            {tags.map((tag, i) => (
                                <span key={i} className="flex items-center gap-1.5 text-xs uppercase font-bold tracking-wider px-3 py-1.5 rounded-full bg-slate-700/50 text-slate-300 border border-slate-600/50">
                                    <Tag size={10} />
                                    {tag}
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* Authors */}
                    <div className="mb-8 p-4 bg-slate-900/50 rounded-xl border border-slate-800">
                        <h3 className="flex items-center gap-2 text-sm font-bold text-slate-500 uppercase tracking-wider mb-3">
                            <Users size={16} /> Authors
                        </h3>
                        <div className="flex flex-wrap gap-x-2 gap-y-1 text-slate-300">
                            {parsedAuthors.map((author, idx) => (
                                <span key={idx} className="hover:text-cyan-400 transition-colors cursor-default">
                                    {author}{idx < parsedAuthors.length - 1 ? ',' : ''}
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* AI Summary */}
                    <div className="mb-10">
                        <div className="flex items-center justify-between gap-4 mb-4">
                            <h3 className="text-xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-400 font-display">
                                AI Analysis
                            </h3>
                            <button
                                onClick={handleRefresh}
                                disabled={refreshing}
                                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-bold transition-all ${refreshing
                                    ? 'bg-slate-700 text-slate-500 cursor-wait'
                                    : 'bg-slate-700/50 text-cyan-400 hover:bg-slate-600 border border-slate-600/50'
                                    }`}
                                title={paper.summary_personalized ? 'Re-summarize with LLM' : 'Summarize with LLM'}
                            >
                                <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
                                {refreshing ? 'Summarizing...' : (paper.summary_personalized ? 'Re-summarize' : 'Summarize')}
                            </button>
                        </div>
                        <div className="prose prose-invert prose-slate max-w-none bg-slate-900/30 p-6 rounded-xl border border-slate-700/50">
                            {paper.summary_personalized ? (
                                <ReactMarkdown
                                    components={{
                                        h2: ({ children }) => <h2 className="text-lg font-bold text-cyan-400 mt-5 mb-2 first:mt-0">{children}</h2>,
                                        h3: ({ children }) => <h3 className="text-base font-bold text-slate-200 mt-4 mb-2">{children}</h3>,
                                        p: ({ children }) => <p className="leading-relaxed text-slate-300 mb-3">{children}</p>,
                                        ul: ({ children }) => <ul className="list-disc list-inside space-y-1 text-slate-300 mb-3">{children}</ul>,
                                        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                                        strong: ({ children }) => <strong className="text-slate-200 font-semibold">{children}</strong>,
                                        code: ({ children }) => <code className="bg-slate-800 px-1.5 py-0.5 rounded text-cyan-300 text-sm">{children}</code>,
                                    }}
                                >
                                    {paper.summary_personalized}
                                </ReactMarkdown>
                            ) : (
                                <p className="text-slate-500 italic">No personalized summary available.</p>
                            )}

                            {paper.score_reason && (
                                <div className="mt-6 pt-6 border-t border-slate-700/50">
                                    <h4 className="text-sm font-bold text-slate-500 uppercase tracking-wider mb-2">Scoring Logic</h4>
                                    <p className="text-sm text-slate-400 font-mono bg-slate-950 p-4 rounded-lg overflow-x-auto">
                                        {paper.score_reason}
                                    </p>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Abstract */}
                    <div>
                        <h3 className="text-xl font-bold text-slate-200 mb-4 font-display">
                            Abstract
                        </h3>
                        <p className="text-slate-400 leading-relaxed text-justify">
                            {paper.summary_generic}
                        </p>
                    </div>
                </article>
            </div>
        </div>
    );
};

export default PaperDetail;

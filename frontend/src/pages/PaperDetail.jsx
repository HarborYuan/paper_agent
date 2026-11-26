import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Calendar, Users, ExternalLink, Star, Building2, Tag, Quote, Check, BookOpen } from 'lucide-react';
import { format } from 'date-fns';
import ReactMarkdown from 'react-markdown';
import ScoreBreakdown from '../components/ScoreBreakdown';
import AuthorList from '../components/AuthorList';
import RelatedPapers from '../components/RelatedPapers';

const API_URL = '/api'; // All backend endpoints live under /api (same origin)

// Only the "## TL;DR" section is shown; older papers may still carry the long structured summary in the DB.
function tldrOnly(md) {
    const text = (md || '').replace(/^```[a-zA-Z]*\n?/i, '').replace(/\n?```$/i, '').trim();
    const lines = text.split('\n');
    const start = lines.findIndex(l => /^##\s*TL;?DR/i.test(l));
    if (start < 0) return text;
    const rest = lines.slice(start + 1);
    const end = rest.findIndex(l => /^##\s/.test(l));
    return (end < 0 ? rest : rest.slice(0, end)).join('\n').trim();
}

const PaperDetail = () => {
    const { id } = useParams();
    const navigate = useNavigate();
    const [paper, setPaper] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [bibState, setBibState] = useState('idle'); // idle | loading | copied | error
    const [bibJournal, setBibJournal] = useState(null);
    const [deepState, setDeepState] = useState('NONE'); // NONE | PENDING | RUNNING | DONE | ERROR | STARTING

    // Deep read (verdict pipeline): bilingual reading page at /read/:id
    const pollDeepRead = () => {
        let attempts = 0;
        const poll = setInterval(async () => {
            attempts++;
            try {
                const res = await axios.get(`${API_URL}/papers/${id}/reading`);
                setDeepState(res.data.status);
                if (res.data.status === 'DONE' || res.data.status === 'ERROR' || attempts >= 60) {
                    clearInterval(poll);
                    if (res.data.status === 'DONE') {
                        const p = await axios.get(`${API_URL}/papers/${id}`);
                        setPaper(p.data);
                    }
                }
            } catch {
                clearInterval(poll);
            }
        }, 5000);
    };

    const handleDeepRead = async () => {
        if (deepState === 'DONE') {
            window.open(`/read/${id}`, '_blank');
            return;
        }
        if (['STARTING', 'PENDING', 'RUNNING'].includes(deepState)) return;
        setDeepState('STARTING');
        try {
            const res = await axios.post(`${API_URL}/papers/${id}/deep-read`);
            setDeepState(res.data.status === 'STARTED' ? 'PENDING' : res.data.status);
            if (res.data.status !== 'DONE') pollDeepRead();
        } catch (err) {
            console.error(err);
            alert(err.response?.data?.detail || 'Failed to start the deep read');
            setDeepState('ERROR');
        }
    };

    useEffect(() => {
        if (!id) return;
        axios.get(`${API_URL}/papers/${id}/reading`).then(res => {
            setDeepState(res.data.status);
            if (res.data.status === 'PENDING' || res.data.status === 'RUNNING') pollDeepRead();
        }).catch(() => {});
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id]);

    // Adds the paper to the BibTeX library (venue auto-detected) and copies the entry
    const handleCopyBibtex = async () => {
        if (bibState === 'loading') return;
        setBibState('loading');
        try {
            const res = await axios.get(`${API_URL}/bibtex/${id}/entry`);
            await navigator.clipboard.writeText(res.data.bibtex);
            setBibJournal(res.data.status === 'published' ? `${res.data.venue} ${res.data.year}` : null);
            setBibState('copied');
            setTimeout(() => setBibState('idle'), 2500);
        } catch (err) {
            console.error(err);
            setBibState('error');
            setTimeout(() => setBibState('idle'), 2500);
        }
    };

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

    // Set document title to arxiv ID
    useEffect(() => {
        if (id) {
            document.title = `${id} - Paper Agent`;
        }
        return () => {
            document.title = 'Paper Agent';
        };
    }, [id]);

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

    // all_categories is stored as a Python-style list string
    let tags = [];
    try {
        tags = JSON.parse(paper.all_categories.replace(/'/g, '"'));
    } catch (e) {
        tags = [paper.category_primary];
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
                    onClick={() => {
                        if (window.history.length > 1) {
                            navigate(-1);
                        } else {
                            window.close();
                        }
                    }}
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
                            {paper.score !== null && paper.score !== undefined && (
                                <div
                                    className={`shrink-0 flex items-center gap-2 px-3 py-1.5 rounded-lg text-lg font-bold ${paper.score >= 85 ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'}`}
                                    title={paper.user_score !== null && paper.user_score !== undefined
                                        ? 'User-assigned score'
                                        : `${paper.score_stage1 !== null && paper.score_stage1 !== undefined ? `Screen ${paper.score_stage1 / 20}/5 → ` : ''}final ${paper.score}${paper.score_model ? ` (${paper.score_model})` : ''}`}
                                >
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
                            <button
                                onClick={handleCopyBibtex}
                                disabled={bibState === 'loading'}
                                className="flex items-center gap-2 text-cyan-400 hover:text-cyan-300 hover:underline transition-colors disabled:cursor-wait"
                                title="Copy BibTeX (with the venue once it has been confirmed as published)"
                            >
                                {bibState === 'copied' ? <Check size={16} /> : <Quote size={16} />}
                                {bibState === 'loading' ? 'Loading…'
                                    : bibState === 'copied' ? `Copied${bibJournal ? ` (${bibJournal})` : ''}`
                                    : bibState === 'error' ? 'BibTeX failed'
                                    : 'BibTeX'}
                            </button>
                            <button
                                onClick={handleDeepRead}
                                disabled={['STARTING', 'PENDING', 'RUNNING'].includes(deepState)}
                                className="flex items-center gap-2 text-cyan-400 hover:text-cyan-300 hover:underline transition-colors disabled:cursor-wait disabled:text-slate-500"
                                title={deepState === 'DONE' ? 'Open the bilingual reading page' : 'Deep read with Claude: verdict, summary, paragraph-by-paragraph Chinese notes and translation (~1-2 min)'}
                            >
                                <BookOpen size={16} />
                                {deepState === 'DONE' ? 'Read'
                                    : ['STARTING', 'PENDING', 'RUNNING'].includes(deepState) ? 'Deep reading…'
                                    : deepState === 'ERROR' ? 'Deep read failed — retry'
                                    : 'Deep read'}
                            </button>
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
                        <p className="text-slate-300 leading-relaxed">
                            <AuthorList authors={paper.authors}
                                linkClassName="hover:text-cyan-400 hover:underline transition-colors cursor-pointer" />
                        </p>
                    </div>

                    {/* AI Summary */}
                    <div className="mb-10">
                        <div className="flex items-center justify-between gap-4 mb-4">
                            <h3 className="text-xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-400 font-display">
                                TL;DR
                            </h3>

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
                                        code: ({ node, className, children, ...props }) => {
                                            const match = /language-(\w+)/.exec(className || '');
                                            return match ? (
                                                <code className={className} {...props}>
                                                    {children}
                                                </code>
                                            ) : (
                                                <code className="bg-slate-800 px-1.5 py-0.5 rounded text-cyan-300 text-sm break-words" {...props}>
                                                    {children}
                                                </code>
                                            );
                                        },
                                        pre: ({ children }) => <pre className="bg-slate-900/50 p-4 rounded-lg overflow-x-auto whitespace-pre-wrap break-words border border-slate-700/50 mb-4">{children}</pre>,
                                    }}
                                >
                                    {tldrOnly(paper.summary_personalized)}
                                </ReactMarkdown>
                            ) : (
                                <p className="text-slate-500 italic">No personalized summary available.</p>
                            )}

                            {paper.score_reason && (
                                <div className="mt-6 pt-6 border-t border-slate-700/50">
                                    <h4 className="text-sm font-bold text-slate-500 uppercase tracking-wider mb-3">Scoring</h4>
                                    <ScoreBreakdown scoreReason={paper.score_reason} userScore={paper.user_score} />
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

                    {/* Related papers (embedding neighbours) */}
                    <RelatedPapers paperId={paper.id} />
                </article>
            </div>
        </div>
    );
};

export default PaperDetail;

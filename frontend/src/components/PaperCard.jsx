import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { FileText, Calendar, Users, Tag, ExternalLink, Star, Building2, RefreshCw, Check, X, Edit2 } from 'lucide-react';
import { format } from 'date-fns';

import axios from 'axios';

// Import Logos
import bytedanceLogo from '../assets/logos/bytedance.svg';
import googleLogo from '../assets/logos/google.svg';
import metaLogo from '../assets/logos/meta.svg';
import alibabaLogo from '../assets/logos/alibaba.svg';
import openaiLogo from '../assets/logos/openai.svg';
import microsoftLogo from '../assets/logos/microsoft.svg';
import deepseekLogo from '../assets/logos/deepseek.svg';
import deepmindLogo from '../assets/logos/deepmind.svg';

const LOGO_MAP = {
    'ByteDance Seed': bytedanceLogo,
    'ByteDance': bytedanceLogo,
    'TikTok': bytedanceLogo,
    'Google DeepMind': deepmindLogo,
    'DeepMind': deepmindLogo,
    'Google': googleLogo,
    'Meta Platforms': metaLogo,
    'Meta Reality Labs': metaLogo,
    'Meta': metaLogo,
    'FAIR': metaLogo,
    'Alibaba': alibabaLogo,
    'DeepSeek': deepseekLogo,
    'OpenAI': openaiLogo,
    'Microsoft': microsoftLogo
};

const MATCH_KEYS = Object.keys(LOGO_MAP)
    .sort((a, b) => b.length - a.length) // Sort by length descending (longest first)
    .map(key => ({
        lower: key.toLowerCase(),
        original: key
    }));

const PaperCard = ({ paper, onRefreshed }) => {

    const [refreshing, setRefreshing] = useState(false);
    const {
        title,
        authors, // Changed from authors_list
        summary_personalized,
        summary_generic,
        published_at,
        score,
        score_reason,
        all_categories,
        pdf_url,
        category_primary,
        main_affiliation,
        main_company,
        user_score
    } = paper;

    const [localScore, setLocalScore] = useState(paper.user_score ?? score);
    const [isEditingScore, setIsEditingScore] = useState(false);
    const [editScoreVal, setEditScoreVal] = useState(localScore || 0);

    const handleScoreClick = (e) => {
        e.stopPropagation();
        setEditScoreVal(localScore || 0);
        setIsEditingScore(true);
    };

    const handleSaveScore = async (e) => {
        e.stopPropagation();
        try {
            const val = parseInt(editScoreVal);
            if (isNaN(val) || val < 0 || val > 100) {
                alert("Score must be 0-100");
                return;
            }
            await axios.patch(`/papers/${paper.id}/score`, null, { params: { score: val } });
            setLocalScore(val);
            setIsEditingScore(false);
            if (onRefreshed) onRefreshed(paper.id); // Potentially trigger parent update
        } catch (error) {
            console.error("Failed to update score", error);
            alert("Failed to update score");
        }
    };

    const handleCancelScore = (e) => {
        e.stopPropagation();
        setIsEditingScore(false);
    };

    // Use personalized summary if available, else generic
    const summary = summary_personalized || summary_generic;
    // Parse tags
    let tags = [];
    try {
        tags = JSON.parse(all_categories.replace(/'/g, '"'));
    } catch (e) {
        tags = [category_primary];
    }

    // Parse Authors
    let parsedAuthors = [];
    if (Array.isArray(authors)) {
        parsedAuthors = authors;
    } else if (typeof authors === 'string') {
        try {
            parsedAuthors = JSON.parse(authors.replace(/'/g, '"'));
        } catch (e) {
            // Fallback or just use the string
            // Remove brackets if it looks like a python list string representation
            let cleaned = authors.replace(/[\[\]']/g, "");
            parsedAuthors = cleaned.split(',').map(s => s.trim().replace(/"/g, ""));
        }
    }

    // Author Shortening Logic
    let displayAuthors = parsedAuthors;
    if (parsedAuthors.length > 4) {
        displayAuthors = [
            ...parsedAuthors.slice(0, 3),
            '...',
            parsedAuthors[parsedAuthors.length - 1]
        ];
    }

    // Format Date (UTC)
    // Ensure the date string is treated as UTC
    const dateStr = published_at.endsWith('Z') ? published_at : `${published_at}Z`;
    const dateObj = new Date(dateStr);
    const formattedDate = format(
        new Date(dateObj.getUTCFullYear(), dateObj.getUTCMonth(), dateObj.getUTCDate()),
        'MMM d, yyyy'
    );

    // Logo Logic
    let logoSrc = null;
    if (main_company) {
        // Clean the company name: trim spaces, lowercase
        const lowerCompany = main_company.toLowerCase();

        // Find longest match in the lowercased keys
        const match = MATCH_KEYS.find(k => lowerCompany.includes(k.lower));
        if (match) {
            logoSrc = LOGO_MAP[match.original];
        }
    }

    const handleRefresh = async (e) => {
        e.stopPropagation();
        if (refreshing) return;
        setRefreshing(true);
        try {
            await axios.post(`/papers/${paper.id}/resummarize`);
            // Poll for completion (check every 3s, up to 120s)
            let attempts = 0;
            const poll = setInterval(async () => {
                attempts++;
                try {
                    const res = await axios.get(`/papers/${paper.id}`);
                    if (res.data.summary_personalized !== paper.summary_personalized || attempts >= 40) {
                        clearInterval(poll);
                        setRefreshing(false);
                        if (onRefreshed) onRefreshed(paper.id);
                        // Force reload the page to show updated data
                        window.location.reload();
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

    return (
        <motion.div
            layout
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            whileHover={{ y: -5, transition: { duration: 0.2 } }}
            onClick={() => window.open(`/paper/${paper.id}`, '_blank')}
            className="bg-slate-800/50 backdrop-blur-md border border-slate-700/50 rounded-xl p-5 shadow-lg hover:shadow-cyan-500/10 hover:border-cyan-500/30 transition-all duration-300 group overflow-hidden relative cursor-pointer"
        >
            {/* Glow Effect */}
            <div className="absolute -inset-0.5 bg-gradient-to-r from-cyan-500 to-purple-600 opacity-0 group-hover:opacity-10 transition duration-500 blur-lg" />

            {/* Header */}
            <div className="relative z-10">
                <div className="flex justify-between items-start gap-2 mb-3">
                    <h3 className="text-lg font-bold text-slate-100 leading-tight group-hover:text-cyan-400 transition-colors pr-8">
                        {title}
                    </h3>
                    {/* Score (Editable) */}
                    <div className="shrink-0 flex items-center gap-1" onClick={e => e.stopPropagation()}>
                        {isEditingScore ? (
                            <div className="flex items-center gap-1 bg-slate-700 rounded px-1 py-0.5">
                                <input
                                    type="number"
                                    min="0"
                                    max="100"
                                    value={editScoreVal}
                                    onChange={(e) => setEditScoreVal(e.target.value)}
                                    className="w-12 bg-slate-900 border border-slate-600 rounded text-xs px-1 text-center text-white focus:outline-none focus:border-cyan-500"
                                    autoFocus
                                    onClick={e => e.stopPropagation()}
                                />
                                <button onClick={handleSaveScore} className="p-0.5 text-green-400 hover:bg-slate-600 rounded"><Check size={12} /></button>
                                <button onClick={handleCancelScore} className="p-0.5 text-red-400 hover:bg-slate-600 rounded"><X size={12} /></button>
                            </div>
                        ) : (
                            localScore !== null ? (
                                <div
                                    onClick={handleScoreClick}
                                    className={`group/score flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold cursor-pointer transition-colors ${localScore >= 85 ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' : 'bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30'}`}
                                    title="Click to edit score"
                                >
                                    <Star size={12} fill="currentColor" />
                                    {localScore}
                                    <Edit2 size={10} className="opacity-0 group-hover/score:opacity-100 transition-opacity ml-1" />
                                </div>
                            ) : (
                                <div
                                    onClick={handleScoreClick}
                                    className="flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold cursor-pointer bg-slate-700 text-slate-400 hover:bg-slate-600 hover:text-white transition-colors"
                                    title="Set score"
                                >
                                    <span className="text-[10px]">Set Score</span>
                                </div>
                            )
                        )}
                    </div>
                    <button
                        onClick={handleRefresh}
                        disabled={refreshing}
                        className="shrink-0 p-1 rounded-full text-slate-500 hover:text-cyan-400 hover:bg-slate-700/50 transition-all disabled:cursor-wait"
                        title={summary_personalized ? 'Re-summarize with LLM' : 'Summarize with LLM'}
                    >
                        <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
                    </button>
                </div>

                {/* Meta */}
                <div className="flex flex-wrap items-center gap-4 text-xs text-slate-400 mb-3">
                    <div className="flex items-center gap-1.5">
                        <Calendar size={12} />
                        <span>{formattedDate}</span>
                    </div>
                    {pdf_url && (
                        <a
                            href={pdf_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1.5 text-cyan-400 hover:text-cyan-300 hover:underline"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <FileText size={12} />
                            <span>PDF</span>
                            <ExternalLink size={10} />
                        </a>
                    )}
                </div>

                {/* Authors */}
                <div className="flex items-start gap-1.5 text-sm text-slate-300 mb-2">
                    <Users size={14} className="mt-0.5 shrink-0 text-slate-500" />
                    <p className="line-clamp-2 text-xs leading-relaxed">
                        {displayAuthors.map((author, idx) => (
                            <span key={idx} className={author === '...' ? 'text-slate-500 mx-1' : ''}>
                                {author}{idx < displayAuthors.length - 1 && author !== '...' ? ', ' : ''}
                            </span>
                        ))}
                    </p>
                </div>

                {/* Affiliation */}
                {(main_affiliation) && (
                    <div className="flex items-center gap-2 mb-3">
                        <div className="flex items-center gap-1.5 text-xs text-slate-400 line-clamp-1">
                            <Building2 size={12} className="shrink-0" />
                            <span>{main_affiliation}</span>
                        </div>
                    </div>
                )}

                {/* Summary */}
                <p className="text-sm text-slate-400 leading-relaxed line-clamp-4 mb-4">
                    {summary}
                </p>

                {/* Footer: Tags + Logo */}
                <div className="flex justify-between items-end mt-4">

                    {/* Tags */}
                    <div className="flex flex-wrap gap-2">
                        {tags.slice(0, 3).map((tag, i) => (
                            <span key={i} className="flex items-center gap-1 text-[10px] uppercase font-bold tracking-wider px-2 py-1 rounded bg-slate-700/50 text-slate-300 border border-slate-600/50">
                                <Tag size={8} />
                                {tag}
                            </span>
                        ))}
                        {tags.length > 3 && (
                            <span className="text-[10px] px-2 py-1 text-slate-500">
                                +{tags.length - 3}
                            </span>
                        )}
                    </div>

                    {/* Company Logo (Bottom Right) */}
                    {logoSrc && (
                        <div className="shrink-0 ml-2 w-32 h-10 flex justify-end items-center">
                            <img
                                src={logoSrc}
                                alt={main_company}
                                className="h-full w-auto object-contain object-right opacity-80 hover:opacity-100 transition-opacity"
                                title={main_company}
                            />
                        </div>
                    )}
                </div>
            </div>
        </motion.div>
    );
};

export default PaperCard;

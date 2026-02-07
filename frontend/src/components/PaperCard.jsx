import React from 'react';
import { motion } from 'framer-motion';
import { FileText, Calendar, Users, Tag, ExternalLink, Star, Building2 } from 'lucide-react';
import { format } from 'date-fns';
import { useNavigate } from 'react-router-dom';

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

const PaperCard = ({ paper }) => {
    const navigate = useNavigate();
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
        main_company
    } = paper;

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

    return (
        <motion.div
            layout
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            whileHover={{ y: -5, transition: { duration: 0.2 } }}
            onClick={() => navigate(`/paper/${paper.id}`)}
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
                    {score && (
                        <div className={`shrink-0 flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold ${score >= 85 ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
                            <Star size={12} fill="currentColor" />
                            {score}
                        </div>
                    )}
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

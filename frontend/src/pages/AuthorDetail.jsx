import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';
import Masonry from 'react-masonry-css';
import { ChevronRight, Users, BookOpen, Search, Calendar } from 'lucide-react';
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
        fetchPapers();
    }, [name, selectedDays]);

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

                <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 pb-8 border-b border-slate-700/50">
                    <div className="flex items-center gap-6">
                        <div className="w-16 h-16 md:w-20 md:h-20 rounded-2xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center text-slate-900 shadow-lg shadow-cyan-500/20">
                            <Users size={40} />
                        </div>
                        <div>
                            <h1 className="text-3xl md:text-4xl font-black text-white mb-2">
                                {name}
                            </h1>
                            <div className="flex items-center gap-4 text-slate-400">
                                <div className="flex items-center gap-1.5 font-medium">
                                    <BookOpen size={16} className="text-cyan-400" />
                                    <span className="text-slate-200 font-bold">{papers.length}</span> Published Papers
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="relative w-full md:w-80">
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

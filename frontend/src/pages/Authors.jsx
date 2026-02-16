import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { motion } from 'framer-motion';
import { Users, BookOpen, ChevronRight, Search, Trophy, Calendar } from 'lucide-react';
import { Link } from 'react-router-dom';

const API_URL = '';

const TIME_RANGES = [
    { label: '7d', value: 7 },
    { label: '30d', value: 30 },
    { label: '90d', value: 90 },
    { label: '180d', value: 180 },
    { label: '360d', value: 360 },
    { label: 'All', value: null },
];

const Authors = () => {
    const [authors, setAuthors] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedDays, setSelectedDays] = useState(7);

    useEffect(() => {
        const fetchAuthors = async () => {
            setIsLoading(true);
            try {
                const params = selectedDays !== null ? { days: selectedDays } : {};
                const res = await axios.get(`${API_URL}/api/authors`, { params });
                setAuthors(res.data);
            } catch (error) {
                console.error("Failed to fetch authors", error);
            } finally {
                setIsLoading(false);
            }
        };
        fetchAuthors();
    }, [selectedDays]);

    const filteredAuthors = authors.filter(author =>
        author.name.toLowerCase().includes(searchQuery.toLowerCase())
    );

    const topAuthors = authors.slice(0, 3);

    return (
        <div className="min-h-screen bg-[#0f172a] text-slate-200 p-6 md:p-12 font-sans">
            <header className="max-w-5xl mx-auto mb-12">
                <Link to="/" className="text-cyan-400 hover:text-cyan-300 mb-6 inline-block font-medium flex items-center gap-2">
                    <ChevronRight size={16} className="rotate-180" />
                    Back to Digest
                </Link>
                <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
                    <div>
                        <h1 className="text-4xl md:text-5xl font-black text-white mb-2">
                            Top <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-500">Authors</span>
                        </h1>
                        <p className="text-slate-400 font-medium font-display">
                            Exploring the minds behind the latest research.
                        </p>
                    </div>

                    <div className="relative w-full md:w-64">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={18} />
                        <input
                            type="text"
                            placeholder="Search authors..."
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

            <main className="max-w-5xl mx-auto">
                {isLoading ? (
                    <div className="flex justify-center py-20">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500"></div>
                    </div>
                ) : (
                    <div className="space-y-8">
                        {/* Highlights */}
                        {searchQuery === '' && topAuthors.length > 0 && (
                            <section className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
                                {topAuthors.map((author, idx) => (
                                    <motion.div
                                        key={author.name}
                                        initial={{ opacity: 0, y: 20 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        transition={{ delay: idx * 0.1 }}
                                        className="bg-gradient-to-br from-slate-800 to-slate-900 p-6 rounded-2xl border border-slate-700 relative overflow-hidden group"
                                    >
                                        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                                            <Trophy size={64} className={idx === 0 ? 'text-yellow-400' : idx === 1 ? 'text-slate-300' : 'text-amber-600'} />
                                        </div>
                                        <div className="relative z-10">
                                            <div className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-2">Rank #{idx + 1}</div>
                                            <h3 className="text-xl font-bold text-white mb-4 line-clamp-1">{author.name}</h3>
                                            <div className="flex items-center gap-2 text-slate-400">
                                                <BookOpen size={16} />
                                                <span className="font-bold text-slate-200">{author.count}</span> Papers
                                            </div>
                                            <Link
                                                to={`/author/${encodeURIComponent(author.name)}`}
                                                className="mt-6 block w-full text-center py-2 rounded-lg bg-slate-700/50 hover:bg-cyan-500 hover:text-slate-900 transition-all font-bold text-xs uppercase tracking-tighter"
                                            >
                                                View All Papers
                                            </Link>
                                        </div>
                                    </motion.div>
                                ))}
                            </section>
                        )}

                        {/* List */}
                        <div className="bg-slate-800/30 rounded-3xl border border-slate-700/50 backdrop-blur-sm overflow-hidden">
                            <div className="grid grid-cols-1 divide-y divide-slate-700/50">
                                {filteredAuthors.length > 0 ? (
                                    filteredAuthors.map((author, idx) => (
                                        <Link
                                            key={author.name}
                                            to={`/author/${encodeURIComponent(author.name)}`}
                                            className="group flex items-center justify-between p-4 md:p-6 hover:bg-slate-700/30 transition-colors"
                                        >
                                            <div className="flex items-center gap-4">
                                                <div className="w-10 h-10 rounded-full bg-slate-700 flex items-center justify-center text-slate-400 group-hover:bg-cyan-500/20 group-hover:text-cyan-400 transition-colors">
                                                    <Users size={20} />
                                                </div>
                                                <div>
                                                    <h4 className="font-bold text-slate-100 group-hover:text-cyan-400 transition-colors">
                                                        {author.name}
                                                    </h4>
                                                    <p className="text-xs text-slate-500 uppercase tracking-widest mt-0.5">Contributor</p>
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-6">
                                                <div className="text-right">
                                                    <div className="text-lg font-black text-white leading-none">{author.count}</div>
                                                    <div className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">Papers</div>
                                                </div>
                                                <ChevronRight className="text-slate-600 group-hover:text-cyan-400 group-hover:translate-x-1 transition-all" size={20} />
                                            </div>
                                        </Link>
                                    ))
                                ) : (
                                    <div className="py-20 text-center">
                                        <Users className="mx-auto mb-4 text-slate-600" size={48} />
                                        <h3 className="text-xl font-bold text-slate-300">No authors found</h3>
                                        <p className="text-slate-500">Try searching for someone else.</p>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
};

export default Authors;

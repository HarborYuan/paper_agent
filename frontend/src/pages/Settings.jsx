import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Settings as SettingsIcon, ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

const API_URL = ''; // Relative path since we serve from the same origin

export default function Settings() {
    const [profile, setProfile] = useState("");
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        const fetchProfile = async () => {
            try {
                const res = await axios.get(`${API_URL}/profile`);
                setProfile(res.data.profile);
            } catch (error) {
                console.error("Failed to fetch profile", error);
                setProfile("Error loading profile. Check backend logs.");
            } finally {
                setIsLoading(false);
            }
        };
        fetchProfile();
    }, []);

    return (
        <div className="min-h-screen bg-[#0f172a] text-slate-200 p-6 md:p-12 font-sans selection:bg-cyan-500/30">
            <div className="max-w-4xl mx-auto">
                {/* Header */}
                <header className="flex items-center gap-4 mb-12">
                    <Link
                        to="/"
                        className="p-2 rounded-full bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
                        title="Back to Home"
                    >
                        <ArrowLeft size={24} />
                    </Link>
                    <div className="flex items-center gap-3">
                        <SettingsIcon size={32} className="text-cyan-400" />
                        <h1 className="text-4xl font-black text-white">Settings</h1>
                    </div>
                </header>

                {/* Content */}
                <div className="bg-slate-800 rounded-2xl border border-slate-700 shadow-xl overflow-hidden">
                    <div className="p-6 md:p-8">
                        <h3 className="text-2xl font-bold text-slate-200 mb-2">User Profile Prompt</h3>
                        <p className="text-slate-400 mb-8 leading-relaxed">
                            This prompt guides the AI in scoring and summarizing papers based on your specific interests.
                            It is currently configured in your <code className="bg-slate-900 px-1.5 py-0.5 rounded text-cyan-400 font-mono text-sm border border-slate-700">.env</code> file.
                        </p>

                        {isLoading ? (
                            <div className="animate-pulse space-y-4">
                                <div className="h-4 bg-slate-700 rounded w-3/4"></div>
                                <div className="h-4 bg-slate-700 rounded"></div>
                                <div className="h-4 bg-slate-700 rounded w-5/6"></div>
                            </div>
                        ) : (
                            <div className="relative">
                                <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-b from-transparent to-slate-900/10 pointer-events-none rounded-xl"></div>
                                <textarea
                                    value={profile}
                                    readOnly
                                    className="w-full h-64 bg-slate-900 border border-slate-700 rounded-xl p-6 text-slate-300 font-mono text-sm focus:outline-none focus:border-cyan-500 transition-colors resize-y shadow-inner leading-relaxed"
                                    placeholder="Loading profile..."
                                />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

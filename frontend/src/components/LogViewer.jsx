import React, { useEffect, useRef } from 'react';
import { X, Trash2, Terminal } from 'lucide-react';

export default function LogViewer({ isOpen, onClose, logs, onClear }) {
    const messagesEndRef = useRef(null);

    // Auto-scroll
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [logs, isOpen]);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-slate-900 rounded-2xl w-full max-w-4xl h-[80vh] flex flex-col shadow-2xl border border-slate-700 font-mono text-sm">

                {/* Header */}
                <div className="flex justify-between items-center p-4 border-b border-slate-700 bg-slate-800/50 rounded-t-2xl">
                    <div className="flex items-center gap-2 text-cyan-400">
                        <Terminal size={20} />
                        <h3 className="font-bold">Backend Logs</h3>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={onClear}
                            className="p-2 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-red-400 transition-colors"
                            title="Clear Logs"
                        >
                            <Trash2 size={18} />
                        </button>
                        <button
                            onClick={onClose}
                            className="p-2 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-white transition-colors"
                        >
                            <X size={20} />
                        </button>
                    </div>
                </div>

                {/* Console Output */}
                <div className="flex-1 overflow-y-auto p-4 space-y-1 bg-[#0d1117] text-slate-300">
                    {logs.length === 0 && (
                        <div className="text-slate-600 italic text-center mt-10">Waiting for logs...</div>
                    )}
                    {logs.map((log, i) => (
                        <div key={i} className="break-words whitespace-pre-wrap border-b border-slate-800/50 pb-0.5 mb-0.5 last:border-0 hover:bg-slate-800/20 px-1">
                            {log}
                        </div>
                    ))}
                    <div ref={messagesEndRef} />
                </div>
            </div>
        </div>
    );
}

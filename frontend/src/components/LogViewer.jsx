import React, { useEffect, useRef } from 'react';
import { X, Trash2, Terminal } from 'lucide-react';

// Backend log stream in a modal, in the `.pa` look (home.css). Rendered inside the home page's `.pa` root.
export default function LogViewer({ isOpen, onClose, logs, onClear }) {
    const messagesEndRef = useRef(null);

    // Auto-scroll
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [logs, isOpen]);

    if (!isOpen) return null;

    return (
        <div className="pa-modal">
            <div className="box pa-logs" role="dialog" aria-label="Backend logs">
                <div className="head">
                    <h3><Terminal size={18} /> Backend Logs</h3>
                    <span className="btns">
                        <button type="button" onClick={onClear} title="Clear Logs"><Trash2 size={17} /></button>
                        <button type="button" onClick={onClose} title="Close"><X size={20} /></button>
                    </span>
                </div>
                <div className="out">
                    {logs.length === 0 && <div className="wait">Waiting for logs...</div>}
                    {logs.map((log, i) => <div key={i} className="ln">{log}</div>)}
                    <div ref={messagesEndRef} />
                </div>
            </div>
        </div>
    );
}

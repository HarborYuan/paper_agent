import React from 'react';
import { motion } from 'framer-motion';
import { RefreshCw } from 'lucide-react';

const DateGroup = ({ dateLabel, onReRank }) => {
    return (
        <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center gap-4 py-8"
        >
            <h2 className="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-purple-400 font-display">
                {dateLabel}
            </h2>
            {onReRank && (
                <button
                    onClick={onReRank}
                    className="p-1.5 rounded-full text-slate-500 hover:text-cyan-400 hover:bg-slate-800 transition-all ml-2"
                    title="Re-score papers for this date"
                >
                    <RefreshCw size={16} />
                </button>
            )}
            <div className="h-px bg-slate-700 flex-1" />
        </motion.div>
    );
};

export default DateGroup;

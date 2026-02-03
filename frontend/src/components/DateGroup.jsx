import React from 'react';
import { motion } from 'framer-motion';

const DateGroup = ({ dateLabel }) => {
    return (
        <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center gap-4 py-8"
        >
            <h2 className="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-purple-400 font-display">
                {dateLabel}
            </h2>
            <div className="h-px bg-slate-700 flex-1" />
        </motion.div>
    );
};

export default DateGroup;

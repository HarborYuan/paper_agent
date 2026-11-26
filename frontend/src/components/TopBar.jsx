import React from 'react';
import { Link } from 'react-router-dom';
import { Settings, FolderKanban, Star } from 'lucide-react';

// The sticky top bar of the pages in the `.pa` look (home.css). Extra nav items go in as children.
const TopBar = ({ children }) => (
    <div className="pa-top">
        <div className="in">
            <Link to="/" className="pa-brand">Paper Agent</Link>
            <nav className="pa-nav">
                <a href="/picks"><Star size={14} />Picks</a>
                <Link to="/projects"><FolderKanban size={14} />Projects</Link>
                <Link to="/settings"><Settings size={14} />Settings</Link>
                {children}
            </nav>
        </div>
    </div>
);

export default TopBar;

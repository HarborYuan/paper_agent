import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { parseAuthors, authorPath } from '../lib/papers';

// Comma-separated author links. With `short`, lists longer than `maxFull` show the first `head`
// names, a "… +N" toggle that expands the full list, and always the last author.
const AuthorList = ({ authors, short = false, head = 4, maxFull = 6, linkClassName = '', moreClassName = '' }) => {
    const [expanded, setExpanded] = useState(false);
    const names = parseAuthors(authors);
    const stop = (e) => e.stopPropagation();
    const link = (name, key) => (
        <Link key={key} to={authorPath(name)} onClick={stop} className={linkClassName}>{name}</Link>
    );
    const cut = short && !expanded && names.length > maxFull;
    if (!cut) {
        return <>{names.map((n, i) => <React.Fragment key={i}>{i > 0 && ', '}{link(n)}</React.Fragment>)}</>;
    }
    const hidden = names.length - head - 1;
    return (
        <>
            {names.slice(0, head).map((n, i) => <React.Fragment key={i}>{i > 0 && ', '}{link(n)}</React.Fragment>)}
            {', '}
            <button type="button" className={moreClassName} title={`Show all ${names.length} authors`}
                onClick={(e) => { e.stopPropagation(); setExpanded(true); }}>
                … +{hidden}
            </button>
            {', '}
            {link(names[names.length - 1])}
        </>
    );
};

export default AuthorList;

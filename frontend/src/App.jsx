import React, { useEffect, useState } from 'react';
import axios from 'axios';
import Masonry from 'react-masonry-css';
import { RefreshCw, Plus, X, Terminal, Users, Settings, Search, Sparkles, FolderKanban, Star } from 'lucide-react';
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';

import DigestCard from './components/DigestCard';
import Feed from './components/Feed';
import { COLUMNS } from './lib/papers';
import PaperDetail from './pages/PaperDetail';
import Authors from './pages/Authors';
import AuthorDetail from './pages/AuthorDetail';
import SettingsPage from './pages/Settings';
import Projects from './pages/Projects';
import LogViewer from './components/LogViewer';
import './home.css';
import PipelineBacklog from './components/PipelineBacklog';

const API_URL = '/api'; // All backend endpoints live under /api (same origin)

function AppContent() {
  const [showLogs, setShowLogs] = useState(false);
  const [logs, setLogs] = useState([]);
  const ws = React.useRef(null);

  useEffect(() => {
    let timeoutId = null;
    let shouldReconnect = true;

    const connect = () => {
      // If already connected, do nothing
      if (ws.current && (ws.current.readyState === WebSocket.OPEN || ws.current.readyState === WebSocket.CONNECTING)) {
        return;
      }

      console.log("Connecting to WebSocket...");
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}${API_URL}/ws/logs`;
      const socket = new WebSocket(wsUrl);
      ws.current = socket;

      socket.onopen = () => {
        setLogs(prev => [...prev, '[System] Connected to log stream...']);
      };

      socket.onmessage = (event) => {
        setLogs(prev => [...prev, event.data]);
      };

      socket.onclose = () => {
        if (shouldReconnect) {
          setLogs(prev => [...prev, '[System] Disconnected from log stream. Reconnecting in 3s...']);
          timeoutId = setTimeout(connect, 3000);
        } else {
          setLogs(prev => [...prev, '[System] Disconnected from log stream.']);
        }
      };

      socket.onerror = (err) => {
        console.error("WS Error", err);
        socket.close(); // Ensure close is called to trigger onclose
      };
    };

    connect();

    return () => {
      shouldReconnect = false;
      if (timeoutId) clearTimeout(timeoutId);
      if (ws.current) {
        ws.current.close();
      }
    };
  }, []);

  const [running, setRunning] = useState(false);
  const [feedKey, setFeedKey] = useState(0);          // bump to reload the digest from the newest day
  const [scoreThreshold, setScoreThreshold] = useState(() => {
    const saved = localStorage.getItem('scoreThreshold');
    return saved !== null ? Number(saved) : 85;
  });
  const [feedThreshold, setFeedThreshold] = useState(scoreThreshold); // the slider value once it settles

  const [showAddModal, setShowAddModal] = useState(false);
  const [addInput, setAddInput] = useState("");
  const [addingPaper, setAddingPaper] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [searchMode, setSearchMode] = useState(() => localStorage.getItem('searchMode') || 'title'); // 'title' | 'semantic'
  const [searchError, setSearchError] = useState(null);
  useEffect(() => { localStorage.setItem('searchMode', searchMode); }, [searchMode]);

  // Debounced Search Effect
  useEffect(() => {
    const handler = setTimeout(async () => {
      const q = searchQuery.trim();
      if (!q) {
        setSearchResults([]);
        setIsSearching(false);
        return;
      }
      setIsSearching(true);
      setSearchError(null);
      try {
        if (searchMode === 'semantic') {
          const res = await axios.get(`${API_URL}/papers/semantic-search`, { params: { q, limit: 30, view: 'card' } });
          setSearchResults(res.data.results || []);
          if (!res.data.index_size) setSearchError('No embeddings yet — run Backfill in Settings → Embeddings.');
        } else {
          const res = await axios.get(`${API_URL}/papers/search`, { params: { q, view: 'card' } });
          setSearchResults(res.data);
        }
      } catch (err) {
        console.error("Failed to search", err);
        setSearchError(err.response?.data?.detail || 'Search failed');
      } finally {
        setIsSearching(false);
      }
    }, searchMode === 'semantic' ? 600 : 400);
    return () => clearTimeout(handler);
  }, [searchQuery, searchMode]);

  // Persist the threshold, and reload the digest once the slider has stopped moving
  useEffect(() => {
    localStorage.setItem('scoreThreshold', String(scoreThreshold));
    const t = setTimeout(() => setFeedThreshold(scoreThreshold), 350);
    return () => clearTimeout(t);
  }, [scoreThreshold]);

  const triggerRun = async () => {
    setRunning(true);
    try {
      await axios.post(`${API_URL}/run`);
      setTimeout(() => {
        setFeedKey(k => k + 1);
        setRunning(false);
      }, 5000);
    } catch (error) {
      console.error("Failed to trigger run", error);
      setRunning(false);
    }
  };

  const handleAddPaper = async (e) => {
    e.preventDefault();
    if (!addInput.trim()) return;

    setAddingPaper(true);
    try {
      const res = await axios.post(`${API_URL}/papers/add`, { input: addInput });
      alert(`Success: ${res.data.message}`);
      setAddInput("");
      setShowAddModal(false);
      setFeedKey(k => k + 1);
    } catch (error) {
      console.error("Failed to add paper", error);
      alert(`Error: ${error.response?.data?.detail || error.message}`);
    } finally {
      setAddingPaper(false);
    }
  };

  const searching = searchQuery.trim() !== "";

  return (
    <div className="pa">
      <LogViewer isOpen={showLogs} onClose={() => setShowLogs(false)} logs={logs} onClear={() => setLogs([])} />

      <div className="pa-top">
        <div className="in">
          <Link to="/" className="pa-brand">Paper Agent</Link>
          <nav className="pa-nav">
            <a href="/picks"><Star size={14} />Picks</a>
            <Link to="/projects"><FolderKanban size={14} />Projects</Link>
            <Link to="/authors"><Users size={14} />Authors</Link>
            <Link to="/settings"><Settings size={14} />Settings</Link>
            <button type="button" onClick={() => setShowLogs(true)} title="View Logs"><Terminal size={14} />Logs</button>
          </nav>
        </div>
      </div>

      <main className="pa-main">
        <section className="pa-hero">
          <div className="pa-kicker">Daily arXiv digest tailored for you · newest publication day first</div>
          <h1>Digest</h1>
          <div className="pa-controls">
            <button type="button" onClick={triggerRun} disabled={running} className="pa-btn primary">
              <RefreshCw size={14} className={running ? 'animate-spin' : ''} />
              {running ? 'Processing…' : 'Fetch New'}
            </button>
            <button type="button" onClick={() => setShowAddModal(true)} className="pa-btn">
              <Plus size={14} /> Add Paper
            </button>
            <label className="pa-range">
              Score ≥
              <input type="range" min={0} max={100} value={scoreThreshold}
                onChange={(e) => setScoreThreshold(Number(e.target.value))} />
              <b>{scoreThreshold}</b>
            </label>
          </div>
          <div className="pa-search">
            <Search className="icon" size={17} />
            <input
              type="text"
              placeholder={searchMode === 'semantic' ? "Describe what you're looking for (e.g. discrete visual tokenizer for unified understanding and generation)…" : "Search titles…"}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <div className="pa-seg" title="Title: substring match on titles. Semantic: embedding similarity on title+abstract (needs embeddings).">
              {[['title', 'Title'], ['semantic', 'Semantic']].map(([m, label]) => (
                <button key={m} type="button" onClick={() => setSearchMode(m)} className={searchMode === m ? 'on' : ''}>
                  {m === 'semantic' && <Sparkles size={12} />}{label}
                </button>
              ))}
            </div>
          </div>
        </section>

        {!searching && <PipelineBacklog />}

        {/* kept mounted while searching, so clearing the search returns to the same place */}
        <div hidden={searching}>
          <Feed key={`${feedThreshold}:${feedKey}`} minScore={feedThreshold} />
        </div>

        {searching && (
          <section>
            <div className="pa-day">
              <h2>{isSearching ? (searchMode === 'semantic' ? 'Searching semantically…' : 'Searching…') : (searchMode === 'semantic' ? 'Semantic matches' : 'Search results')}</h2>
              {!isSearching && <small>{searchResults.length} papers</small>}
              {searchError && <small className="pa-warn">{searchError}</small>}
              <span className="rule" />
            </div>
            {searchResults.length > 0 ? (
              <Masonry breakpointCols={COLUMNS} className="pa-grid" columnClassName="pa-col">
                {searchResults.map(paper => <DigestCard key={paper.id} paper={paper} similarity={paper.similarity} />)}
              </Masonry>
            ) : (
              !isSearching && (
                <div className="pa-empty">
                  <h3>No results found</h3>
                  <p>Try a different {searchMode === 'semantic' ? 'description' : 'title'}.</p>
                </div>
              )
            )}
          </section>
        )}
      </main>

      {showAddModal && (
        <div className="pa-modal" onClick={() => setShowAddModal(false)}>
          <div className="box" onClick={e => e.stopPropagation()}>
            <div className="head">
              <h3>Add Paper</h3>
              <button type="button" onClick={() => setShowAddModal(false)} title="Close"><X size={20} /></button>
            </div>
            <form onSubmit={handleAddPaper}>
              <label htmlFor="add-paper-input">arXiv ID or URL</label>
              <input
                id="add-paper-input"
                type="text"
                value={addInput}
                onChange={(e) => setAddInput(e.target.value)}
                placeholder="e.g. 1512.03385 or https://arxiv.org/abs/1512.03385"
                autoFocus
              />
              <p className="hint">Supports abstract URLs and PDF URLs.</p>
              <div className="actions">
                <button type="button" onClick={() => setShowAddModal(false)} className="pa-btn">Cancel</button>
                <button type="submit" disabled={addingPaper || !addInput.trim()} className="pa-btn primary">
                  {addingPaper ? 'Adding…' : 'Add Paper'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppContent />} />
        <Route path="/paper/:id" element={<PaperDetail />} />
        <Route path="/authors" element={<Authors />} />
        <Route path="/author/:name" element={<AuthorDetail />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;

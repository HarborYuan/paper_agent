import React, { useEffect, useState, useRef } from 'react';
import axios from 'axios';
import { format, subDays, isToday, isYesterday } from 'date-fns';
import Masonry from 'react-masonry-css';
import { RefreshCw, Zap, Plus, X, Terminal } from 'lucide-react';
import { useInView } from 'react-intersection-observer';
import { BrowserRouter, Routes, Route } from 'react-router-dom';

import PaperCard from './components/PaperCard';
import DateGroup from './components/DateGroup';
import PaperDetail from './pages/PaperDetail';
import LogViewer from './components/LogViewer';

const API_URL = ''; // Relative path since we serve from the same origin in Docker/Production

function AppContent() {
  const [groups, setGroups] = useState([]); // Array of { date: Date, papers: Paper[] }
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
      const wsUrl = `${protocol}//${window.location.host}/ws/logs`;
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

  const [cursorDate, setCursorDate] = useState(new Date());
  const [isLoading, setIsLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [running, setRunning] = useState(false);
  const [scoreThreshold, setScoreThreshold] = useState(() => {
    const saved = localStorage.getItem('scoreThreshold');
    return saved !== null ? Number(saved) : 85;
  });

  const [showAddModal, setShowAddModal] = useState(false);
  const [addInput, setAddInput] = useState("");
  const [addingPaper, setAddingPaper] = useState(false);

  const [startDate, setStartDate] = useState(null); // Earliest paper date

  // Intersection observer for infinite scroll
  const { ref: observerRef, inView } = useInView({
    threshold: 0,
    rootMargin: '400px', // Load before reaching bottom
  });

  // Load next day when inView
  useEffect(() => {
    if (inView && !isLoading && hasMore && groups.length > 0) {
      loadNextDay();
    }
  }, [inView, isLoading, hasMore, groups]);

  // Persist threshold to localStorage
  useEffect(() => {
    localStorage.setItem('scoreThreshold', String(scoreThreshold));
  }, [scoreThreshold]);

  // Initial load
  useEffect(() => {
    // Fetch earliest date first
    const fetchMeta = async () => {
      try {
        const res = await axios.get(`${API_URL}/papers/start-date`);
        if (res.data.date) {
          const [y, m, d] = res.data.date.split('-').map(Number);
          setStartDate(new Date(y, m - 1, d));
        }
      } catch (e) {
        console.error("Failed to fetch start date", e);
      }
    };
    fetchMeta();

    loadNextDay(new Date());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Ref to track fetching state to prevent race conditions
  const isFetching = React.useRef(false);

  const loadNextDay = async (startTime = null) => {
    // Check ref instead of state for immediate feedback
    if (isFetching.current || !hasMore) return;

    isFetching.current = true;
    setIsLoading(true);

    let targetDate = startTime || cursorDate;

    // Stop if we went past start date
    if (startDate && targetDate < startDate) {
      setHasMore(false);
      setIsLoading(false);
      isFetching.current = false;
      return;
    }

    try {
      const dateStr = format(targetDate, 'yyyy-MM-dd');
      console.log(`Checking next available date from ${dateStr}...`);

      // Find the next date with papers (inclusive of targetDate)
      const nextDateRes = await axios.get(`${API_URL}/papers/next-date`, {
        params: { date: dateStr }
      });

      const nextDateStr = nextDateRes.data.date;

      if (!nextDateStr) {
        console.log("No more papers found.");
        setHasMore(false);
        setIsLoading(false);
        isFetching.current = false;
        return;
      }

      console.log(`Fetching papers for ${nextDateStr}`);
      const res = await axios.get(`${API_URL}/papers`, {
        params: { date: nextDateStr }
      });

      const papers = res.data;
      // Sort by score
      papers.sort((a, b) => (b.score || 0) - (a.score || 0));

      if (papers.length > 0) {
        // Parse "YYYY-MM-DD" manually to ensure local time (avoiding UTC conversion shift)
        const [y, m, d] = nextDateStr.split('-').map(Number);
        const nextDateObj = new Date(y, m - 1, d);

        setGroups(prev => {
          // Deduplicate
          const existingDates = new Set(prev.map(g => g.date.toISOString()));
          // We are only adding one group
          if (existingDates.has(nextDateObj.toISOString())) {
            return prev;
          }
          return [...prev, { date: nextDateObj, papers }];
        });

        // Prepare cursor for NEXT iteration (one day before the one we just fetched)
        setCursorDate(subDays(nextDateObj, 1));
      } else {
        // This shouldn't theoretically happen if next-date returned a date, 
        // unless papers were deleted between calls or logic mismatch.
        // Just advance cursor to avoid loop.
        setCursorDate(subDays(new Date(nextDateStr), 1));
      }

    } catch (error) {
      console.error("Failed to fetch papers", error);
    } finally {
      setIsLoading(false);
      isFetching.current = false;
    }
  };

  const triggerRun = async () => {
    setRunning(true);
    try {
      await axios.post(`${API_URL}/run`);
      setTimeout(() => {
        // Reset and reload
        setGroups([]);
        setCursorDate(new Date());
        loadNextDay(new Date());
        setRunning(false);
      }, 5000);
    } catch (error) {
      console.error("Failed to trigger run", error);
      setRunning(false);
    }
  };

  const handleReScoreDate = async (date) => {
    const dateStr = format(date, 'yyyy-MM-dd');
    const confirm = window.confirm(`Are you sure you want to re-score all papers from ${dateStr}?`);
    if (!confirm) return;

    try {
      await axios.post(`${API_URL}/papers/re-score-date`, null, {
        params: { date: dateStr }
      });
      alert(`Re-scoring started for ${dateStr}. Please refresh in a few moments.`);
    } catch (error) {
      console.error("Failed to re-score date", error);
      alert("Failed to trigger re-scoring.");
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

      setGroups([]);
      setCursorDate(new Date());
      loadNextDay(new Date());
    } catch (error) {
      console.error("Failed to add paper", error);
      alert(`Error: ${error.response?.data?.detail || error.message}`);
    } finally {
      setAddingPaper(false);
    }
  };

  // Filter papers for display
  const getFilteredGroupPapers = (groupPapers) => {
    return groupPapers.filter(paper => {
      return (paper.score || 0) >= scoreThreshold;
    });
  };

  // Refresh a single paper's data in the local state
  const handlePaperRefreshed = (paperId) => {
    // Re-fetch the group containing this paper
    setGroups(prevGroups => prevGroups.map(group => ({
      ...group,
      papers: group.papers.map(p => p.id === paperId ? { ...p, _refreshing: false } : p)
    })));
  };



  const masonryBreakpoints = {
    default: 3,
    1100: 2,
    700: 1
  };




  return (
    <div className="min-h-screen bg-[#0f172a] text-slate-200 p-6 md:p-12 font-sans selection:bg-cyan-500/30">

      <LogViewer isOpen={showLogs} onClose={() => setShowLogs(false)} logs={logs} onClear={() => setLogs([])} />

      {/* Header */}
      <header className="max-w-7xl mx-auto mb-12 flex justify-between items-end">
        <div>
          <h1 className="text-4xl md:text-5xl font-black tracking-tight text-white mb-2 font-display">
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-500">Paper</span>
            Agent
          </h1>
          <p className="text-slate-400 font-medium">
            Daily arXiv digest tailored for you.
          </p>
        </div>

        <div className="flex items-center gap-4">
          {/* Logs Button */}
          <button
            onClick={() => setShowLogs(true)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg font-bold bg-slate-800 text-cyan-400 hover:bg-slate-700 transition-all border border-slate-700"
            title="View Logs"
          >
            <Terminal size={18} />
          </button>

          {/* Threshold Slider */}
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-slate-400">Score ≥</span>
            <input
              type="range"
              min={0}
              max={100}
              value={scoreThreshold}
              onChange={(e) => setScoreThreshold(Number(e.target.value))}
              className="w-24 h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-cyan-500"
            />
            <span className="text-sm font-bold text-cyan-400 w-8 text-center tabular-nums">{scoreThreshold}</span>
          </div>

          <button
            onClick={triggerRun}
            disabled={running}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg font-bold transition-all ${running ? 'bg-slate-700 text-slate-500 cursor-wait' : 'bg-cyan-500 text-slate-900 hover:bg-cyan-400 shadow-lg hover:shadow-cyan-500/25'}`}
          >
            <RefreshCw size={18} className={running ? 'animate-spin' : ''} />
            {running ? 'Processing...' : 'Fetch New'}
          </button>

          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg font-bold bg-slate-700 text-slate-200 hover:bg-slate-600 transition-all"
          >
            <Plus size={18} />
            Add Paper
          </button>
        </div>
      </header>

      {/* Add Paper Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-slate-800 rounded-2xl p-6 w-full max-w-md shadow-2xl border border-slate-700">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xl font-bold text-white">Add Paper</h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X size={24} />
              </button>
            </div>

            <form onSubmit={handleAddPaper}>
              <div className="mb-4">
                <label className="block text-slate-400 text-sm font-bold mb-2">
                  arXiv ID or URL
                </label>
                <input
                  type="text"
                  value={addInput}
                  onChange={(e) => setAddInput(e.target.value)}
                  placeholder="e.g. 1512.03385 or https://arxiv.org/abs/1512.03385"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-cyan-500 transition-colors"
                  autoFocus
                />
                <p className="text-xs text-slate-500 mt-2">
                  Supports abstract URLs and PDF URLs.
                </p>
              </div>

              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 rounded-lg font-medium text-slate-300 hover:bg-slate-700 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={addingPaper || !addInput.trim()}
                  className={`px-4 py-2 rounded-lg font-bold text-slate-900 transition-colors ${addingPaper || !addInput.trim() ? 'bg-slate-600 cursor-not-allowed' : 'bg-cyan-500 hover:bg-cyan-400'}`}
                >
                  {addingPaper ? 'Adding...' : 'Add Paper'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Content */}
      <main className="max-w-7xl mx-auto space-y-8 pb-20">
        {groups.map((group, index) => {
          const visiblePapers = getFilteredGroupPapers(group.papers);
          if (visiblePapers.length === 0) return null;

          let label = format(group.date, 'MMMM d, yyyy');
          if (isToday(group.date)) label = "Today";
          if (isYesterday(group.date)) label = "Yesterday";

          return (
            <section key={group.date.toISOString()}>
              <DateGroup
                dateLabel={label}
                onReRank={() => handleReScoreDate(group.date)}
              />
              <Masonry
                breakpointCols={masonryBreakpoints}
                className="flex -ml-6 w-auto"
                columnClassName="pl-6 bg-clip-padding space-y-6"
              >
                {visiblePapers.map(paper => (
                  <PaperCard key={paper.id} paper={paper} onRefreshed={handlePaperRefreshed} />
                ))}
              </Masonry>
            </section>
          );
        })}

        {/* Loading / Sentinel */}
        <div ref={observerRef} className="flex justify-center py-10 opacity-50">
          {isLoading && <RefreshCw className="animate-spin" size={30} />}
          {!isLoading && hasMore && groups.length > 0 && <span className="text-sm">Load more...</span>}
        </div>

        {/* Initial Empty State */}
        {!isLoading && groups.length === 0 && (
          <div className="text-center py-20 bg-slate-800/30 rounded-3xl border border-slate-700 border-dashed">
            <Zap className="mx-auto mb-4 text-slate-600" size={48} />
            <h3 className="text-xl font-bold text-slate-300">No papers found</h3>
            <p className="text-slate-500">Trigger a fetch to get started.</p>
          </div>
        )}
      </main>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppContent />} />
        <Route path="/paper/:id" element={<PaperDetail />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;

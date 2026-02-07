import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { format, subDays, isSameDay, isToday, isYesterday } from 'date-fns';
import Masonry from 'react-masonry-css';
import { RefreshCw, Zap, ArrowDown, Plus, X } from 'lucide-react';
import { useInView } from 'react-intersection-observer';
import PaperCard from './components/PaperCard';
import DateGroup from './components/DateGroup';

const API_URL = 'http://localhost:8000';

function App() {
  const [groups, setGroups] = useState([]); // Array of { date: Date, papers: Paper[] }
  const [cursorDate, setCursorDate] = useState(new Date());
  const [isLoading, setIsLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [running, setRunning] = useState(false);
  const [showLowScore, setShowLowScore] = useState(false);

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

  // Initial load
  useEffect(() => {
    // Fetch earliest date first
    const fetchMeta = async () => {
      try {
        const res = await axios.get(`${API_URL}/papers/start-date`);
        if (res.data.date) {
          setStartDate(new Date(res.data.date));
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

    let daysTried = 0;
    let foundPapers = false;
    let newGroups = [];

    // Recursive-ish fetch loop to skip empty days (limit to 3 empty days at a time to prevent endless loop)
    // Actually, safer to just fetch one day and let the UI trigger next if empty, but to avoid empty sections, 
    // let's try to fetch until we find papers or hit a limit (e.g. 5 days back).

    // Current strategy: Fetch ONE day. If it's empty, we still render the date header (or not?), 
    // and let the observer trigger the next day immediately if it's still in view.
    // Ideally we want to prevent rendering empty sections. 

    try {
      while (daysTried < 5 && !foundPapers) {

        // Double check against start date inside loop
        if (startDate && targetDate < startDate) {
          setHasMore(false);
          break;
        }

        const dateStr = format(targetDate, 'yyyy-MM-dd');
        console.log(`Fetching for ${dateStr}`);

        try {
          const res = await axios.get(`${API_URL}/papers`, {
            params: { date: dateStr } // No limiting needed as we want full day
          });

          const papers = res.data;
          if (papers.length > 0) {
            // Client-side filtering for low scores happens during render, 
            // but we need to know if we effectively have papers to show?
            // Actually the API returns everything. 
            // Let's rely on the raw count. 

            // Sort by score
            papers.sort((a, b) => (b.score || 0) - (a.score || 0));

            newGroups.push({
              date: targetDate, // Store as Date object
              papers: papers
            });
            foundPapers = true;
          }
        } catch (e) {
          console.error(`Error fetching ${dateStr}`, e);
        }

        // Prepare for next iteration
        targetDate = subDays(targetDate, 1);
        daysTried++;
      }

      if (newGroups.length > 0) {
        setGroups(prev => {
          // Deduplicate: check if we already have a group for this date
          const existingDates = new Set(prev.map(g => g.date.toISOString()));
          const uniqueNewGroups = newGroups.filter(g => !existingDates.has(g.date.toISOString()));

          if (uniqueNewGroups.length === 0) {
            return prev;
          }
          return [...prev, ...uniqueNewGroups];
        });
      } else {
        // If we tried 5 days and found nothing, maybe stop? 
        // Or just stop for this batch. The user can scroll more (if we didn't block it).
        // Since we updated cursorDate, next trigger will continue from there.
        // If we really found NOTHING for 5 days, it's likely we reached the end of time/data. 
        // But let's verify if we should set hasMore=false. 
        // For now, let's just assume there might be more later. 
        // However, if we don't add content, the page height won't grow, so observer might stay in view, triggering loop.
        // To permit checking deeper history, we must update cursor.
      }

      setCursorDate(targetDate);

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
      if (showLowScore) return true;
      return (paper.score || 0) >= 85;
    });
  };

  const masonryBreakpoints = {
    default: 3,
    1100: 2,
    700: 1
  };

  return (
    <div className="min-h-screen bg-[#0f172a] text-slate-200 p-6 md:p-12 font-sans selection:bg-cyan-500/30">

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
          {/* Toggle */}
          <div className="flex items-center gap-2">
            <span className={`text-sm font-medium ${showLowScore ? 'text-slate-200' : 'text-slate-500'}`}>Low Scores</span>
            <button
              onClick={() => setShowLowScore(!showLowScore)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${showLowScore ? 'bg-cyan-500' : 'bg-slate-700'}`}
            >
              <span
                className={`${showLowScore ? 'translate-x-6' : 'translate-x-1'} inline-block h-4 w-4 transform rounded-full bg-white transition-transform`}
              />
            </button>
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
              <DateGroup dateLabel={label} />
              <Masonry
                breakpointCols={masonryBreakpoints}
                className="flex -ml-6 w-auto"
                columnClassName="pl-6 bg-clip-padding space-y-6"
              >
                {visiblePapers.map(paper => (
                  <PaperCard key={paper.id} paper={paper} />
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

export default App;

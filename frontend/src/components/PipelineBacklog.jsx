import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { AlertTriangle, RotateCcw, Hourglass, ChevronDown, ChevronRight, BookOpen } from 'lucide-react';

const API_URL = '/api';
const VERDICT = { must_read: 'Must Read', worth_reading: 'Worth Reading' };

// What the pipeline still owes: failed deep reads (retried next run, or given up after repeated
// failures) and the queues. Hidden when there is nothing to show.
const PipelineBacklog = () => {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(true);
  const [busy, setBusy] = useState({});

  const load = () => axios.get(`${API_URL}/pipeline/backlog`).then(res => setData(res.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const deepRead = async (id) => {
    setBusy(b => ({ ...b, [id]: 'Starting…' }));
    try {
      await axios.post(`${API_URL}/papers/${id}/deep-read`, null, { params: { force: true } });
      setBusy(b => ({ ...b, [id]: 'Started' }));
    } catch (e) {
      setBusy(b => ({ ...b, [id]: e.response?.data?.detail || 'Failed' }));
    }
  };

  if (!data) return null;
  const { deep_retry: retry, deep_gave_up: gaveUp, deep_waiting: waiting, review_pending: review, screen_pending: screen } = data;
  const counts = [
    waiting.length && `${waiting.length} waiting for a deep-read slot`,
    review.length && `${review.length} waiting for a review`,
    screen && `${screen} not screened yet`,
  ].filter(Boolean);
  if (!retry.length && !gaveUp.length && !counts.length) return null;

  const Row = ({ x, action }) => (
    <li className="flex items-start gap-3 py-2 border-t border-slate-700/60 first:border-t-0">
      <div className="min-w-0 flex-1">
        <Link to={`/paper/${x.id}`} className="text-sm font-semibold text-slate-200 hover:text-cyan-400">{x.title}</Link>
        <div className="text-xs text-slate-500 mt-0.5">
          {x.id}{VERDICT[x.verdict] ? ` · ${VERDICT[x.verdict]}` : ''}{x.failures ? ` · failed ${x.failures}×` : ''}
        </div>
        {x.error && <div className="text-xs text-amber-400/90 mt-0.5 break-words">{x.error}</div>}
      </div>
      {action && (
        busy[x.id]
          ? <span className="text-xs text-slate-400 whitespace-nowrap pt-1">{busy[x.id]}</span>
          : <button onClick={() => deepRead(x.id)}
              className="flex items-center gap-1 text-xs font-bold px-2.5 py-1 rounded-md bg-slate-700 text-slate-200 hover:bg-slate-600 whitespace-nowrap">
              <BookOpen size={13} /> Deep read
            </button>
      )}
    </li>
  );

  return (
    <section className="max-w-7xl mx-auto mb-8 rounded-2xl border border-amber-500/30 bg-amber-500/5">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center gap-2 px-5 py-3 text-left">
        {open ? <ChevronDown size={18} className="text-amber-400" /> : <ChevronRight size={18} className="text-amber-400" />}
        <AlertTriangle size={18} className="text-amber-400" />
        <span className="font-bold text-amber-200">Still to do</span>
        <span className="text-sm text-slate-400">
          {[retry.length && `${retry.length} retrying`, gaveUp.length && `${gaveUp.length} need a manual deep read`, ...counts].filter(Boolean).join(' · ')}
        </span>
      </button>
      {open && (
        <div className="px-5 pb-4 space-y-4">
          {retry.length > 0 && (
            <div>
              <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-slate-400 mb-1">
                <RotateCcw size={13} /> Deep read failed — retried on the next run
              </h3>
              <ul>{retry.map(x => <Row key={x.id} x={x} action />)}</ul>
            </div>
          )}
          {gaveUp.length > 0 && (
            <div>
              <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-slate-400 mb-1">
                <AlertTriangle size={13} /> Deep read failed repeatedly — no more automatic retries
              </h3>
              <ul>{gaveUp.map(x => <Row key={x.id} x={x} action />)}</ul>
            </div>
          )}
          {counts.length > 0 && (
            <p className="flex items-center gap-1.5 text-sm text-slate-400">
              <Hourglass size={14} /> Queued for the next run: {counts.join('; ')}.
            </p>
          )}
        </div>
      )}
    </section>
  );
};

export default PipelineBacklog;

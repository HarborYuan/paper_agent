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
    <li>
      <div className="txt">
        <Link to={`/paper/${x.id}`}>{x.title}</Link>
        <div className="pa-meta">
          {x.id}{VERDICT[x.verdict] ? ` · ${VERDICT[x.verdict]}` : ''}{x.failures ? ` · failed ${x.failures}×` : ''}
        </div>
        {x.error && <div className="err">{x.error}</div>}
      </div>
      {action && (
        busy[x.id]
          ? <span className="pa-meta">{busy[x.id]}</span>
          : <button type="button" onClick={() => deepRead(x.id)} className="pa-btn small"><BookOpen size={13} /> Deep read</button>
      )}
    </li>
  );

  return (
    <section className="pa-panel">
      <button type="button" onClick={() => setOpen(o => !o)} className="pa-panel-head">
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <AlertTriangle size={16} className="warn" />
        <span className="title">Still to do</span>
        <span className="pa-meta">
          {[retry.length && `${retry.length} retrying`, gaveUp.length && `${gaveUp.length} need a manual deep read`, ...counts].filter(Boolean).join(' · ')}
        </span>
      </button>
      {open && (
        <div className="pa-panel-body">
          {retry.length > 0 && (
            <div>
              <h4><RotateCcw size={12} /> Deep read failed — retried on the next run</h4>
              <ul>{retry.map(x => <Row key={x.id} x={x} action />)}</ul>
            </div>
          )}
          {gaveUp.length > 0 && (
            <div>
              <h4><AlertTriangle size={12} /> Deep read failed repeatedly — no more automatic retries</h4>
              <ul>{gaveUp.map(x => <Row key={x.id} x={x} action />)}</ul>
            </div>
          )}
          {counts.length > 0 && (
            <p className="pa-meta"><Hourglass size={13} /> Queued for the next run: {counts.join('; ')}.</p>
          )}
        </div>
      )}
    </section>
  );
};

export default PipelineBacklog;

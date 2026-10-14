import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { api, apiUrl } from '../api';
import { Badge, Loading, Err, Page } from '../components';

export default function TargetDossier() {
  const { id } = useParams();
  const [review, setReview] = useState({ review_status: 'Under review', reviewer: '', review_notes: '' });
  const [msg, setMsg] = useState('');
  const q = useQuery({ queryKey: ['target', id], queryFn: () => api.get<any>(`/targets/${id}/dossier`) });

  async function submitReview() {
    setMsg('');
    try {
      await api.patch(`/targets/${id}/review`, review);
      setMsg('Review saved.');
      q.refetch();
    } catch (e: any) { setMsg(`Error: ${e.message}`); }
  }

  if (q.isLoading) return <Page title="Target dossier"><Loading what="dossier" /></Page>;
  if (q.isError) return <Page title="Target dossier"><Err message={(q.error as Error).message} /></Page>;
  const d = q.data!;
  const ev = d.evidence ?? {};
  const gate = d.evidence_gate;
  const cits: Record<string, string> = d.occurrence_citations ?? {};
  const bars = Object.entries(ev.per_layer ?? {}).map(([k, v]) => ({ layer: k, score: v == null ? 0 : +(v as number).toFixed(3), missing: v == null }));

  return (
    <Page title={`Target #${d.rank} — ${d.commodity} dossier`} sub="Why it scored high, what is missing, and what to do next.">
      {gate && !gate.sufficient && (
        <div className="card border-orange-700 text-sm">
          <div className="font-medium text-orange-300">INSUFFICIENT EVIDENCE — not a targeting result.</div>
          <div className="font-mono text-xs text-neutral-400">Missing groups: {(gate.missing_groups ?? []).join(', ')}</div>
        </div>
      )}
      <div className="card font-mono text-xs space-y-1">
        <div>ID {d.id} · run {d.run?.id} ({d.run?.method}) · <Badge label={d.status_label} /> · review: {d.review_status}</div>
        <div>Centroid {d.centroid.lat.toFixed(5)}, {d.centroid.lon.toFixed(5)} (DD) · E {d.centroid.easting.toLocaleString()} N {d.centroid.northing.toLocaleString()} (UTM 36S)</div>
        <div>Area {d.area_m2.toLocaleString()} m² · mean {d.mean_score.toFixed(3)} · max {d.max_score.toFixed(3)} · coverage {(d.coverage * 100).toFixed(0)}%</div>
      </div>

      <div className="card">
        <div className="font-medium mb-2">Score breakdown per evidence layer</div>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={bars} layout="vertical">
            <XAxis type="number" domain={[0, 1]} />
            <YAxis type="category" dataKey="layer" width={120} />
            <Tooltip />
            <Bar dataKey="score">{bars.map((b, i) => <Cell key={i} fill={b.missing ? '#525252' : '#d9a441'} />)}</Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="grid md:grid-cols-3 gap-3">
        <div className="card"><div className="label">Supporting</div><ul className="text-sm list-disc ml-4">{(ev.supporting ?? []).map((s: string) => <li key={s}>{s}</li>) || '—'}</ul></div>
        <div className="card"><div className="label">Conflicting</div><ul className="text-sm list-disc ml-4">{(ev.conflicting ?? []).map((s: string) => <li key={s}>{s}</li>) || '—'}</ul></div>
        <div className="card"><div className="label">Missing evidence</div><ul className="text-sm list-disc ml-4">{(ev.missing_evidence ?? []).map((s: string) => <li key={s}>{s}</li>) || '—'}</ul></div>
      </div>

      <div className="card">
        <div className="label">Constraints check</div>
        {ev.constraints?.clean
          ? <p className="text-sm text-emerald-300">Clean — {ev.constraints.note ?? 'no overlaps with stored constraint layers.'}</p>
          : <ul className="text-sm text-red-300 list-disc ml-4">{(ev.constraints?.conflicts ?? []).map((c: any, i: number) => <li key={i}>{c.type} — {c.name}</li>)}</ul>}
      </div>

      <div className="card">
        <div className="label">Recommended next steps (rules-based)</div>
        <ol className="text-sm list-decimal ml-4">{(ev.next_steps ?? []).map((s: string, i: number) => <li key={i}>{s}</li>)}</ol>
      </div>

      {Object.keys(cits).length > 0 && (
        <div className="card">
          <div className="label">Occurrence citations (literature records behind this run)</div>
          <ul className="text-sm list-disc ml-4">{Object.entries(cits).map(([n, c]) => <li key={n}><span className="font-medium">{n}:</span> {c}</li>)}</ul>
        </div>
      )}

      <div className="card space-y-2">
        <div className="font-medium">Review workflow <span className="text-neutral-500 text-xs">(Admin/Geologist; sign-off flips MODEL OUTPUT → REVIEWED)</span></div>
        <div className="grid md:grid-cols-3 gap-2">
          <select className="input" value={review.review_status} onChange={(e) => setReview({ ...review, review_status: e.target.value })}>
            {['Proposed', 'Under review', 'Field verified', 'Rejected', 'Advanced'].map((s) => <option key={s}>{s}</option>)}
          </select>
          <input className="input" placeholder="Reviewer name" value={review.reviewer} onChange={(e) => setReview({ ...review, reviewer: e.target.value })} />
          <input className="input" placeholder="Notes" value={review.review_notes} onChange={(e) => setReview({ ...review, review_notes: e.target.value })} />
        </div>
        <div className="flex gap-2 items-center">
          <button className="btn" onClick={submitReview}>Save review</button>
          <a className="btn-ghost" href={apiUrl(`/targets/${d.id}/dossier.pdf`)}>Download PDF</a>
          {msg && <span className="text-sm text-neutral-300">{msg}</span>}
        </div>
      </div>
    </Page>
  );
}

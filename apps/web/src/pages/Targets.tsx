import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, Run, Target } from '../api';
import { Badge, Empty, Loading, Err, Page } from '../components';
import { useUI } from '../store';

export default function Targets() {
  const { projectId, runId } = useUI();
  const setRun = useUI((s) => s.setRun);
  const runs = useQuery({
    queryKey: ['runs', projectId],
    queryFn: () => api.get<{ total: number; items: Run[] }>(`/runs?project_id=${projectId}`),
    enabled: !!projectId,
  });
  // default: latest completed run for the active project
  useEffect(() => {
    if (!runs.data || runId) return;
    const done = runs.data.items.filter((r) => r.status === 'done');
    if (done.length) setRun(done[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs.data]);
  const q = useQuery({
    queryKey: ['targets', runId],
    queryFn: () => api.get<{ total: number; items: Target[] }>(`/targets?run_id=${runId}`),
    enabled: !!runId,
  });

  if (!projectId) return <Page title="Targets"><Empty title="No project selected" hint="Pick one on the Workspace page." /></Page>;
  const selRun = runs.data?.items.find((r) => r.id === runId);
  const gate = (selRun?.metrics as any)?.evidence_gate;
  const insufficient = gate && !gate.sufficient;
  return (
    <Page title="Ranked targets" sub={runId ? `Run ${runId} — relative rankings, not deposit probabilities.` : 'Pick a run.'}>
      {insufficient && (
        <div className="card border-orange-700 text-sm">
          <div className="font-medium text-orange-300">INSUFFICIENT EVIDENCE — not a targeting result.</div>
          <div className="font-mono text-xs text-neutral-400 mt-1">Missing groups: {(gate.missing_groups ?? []).join(', ')}. The surface is for inspection only — import {['structure', 'host_lithology', 'alteration_or_geochem'].filter((g) => (gate.missing_groups ?? []).includes(g)).join(', ') || 'the missing evidence'} before targeting.</div>
        </div>
      )}
      <div className="flex gap-2 items-center">
        <span className="label">Run</span>
        <select className="input max-w-md" value={runId ?? ''} onChange={(e) => setRun(e.target.value || null)}>
          <option value="">— select run —</option>
          {(runs.data?.items ?? []).map((r) => (
            <option key={r.id} value={r.id}>{r.method} · {r.status} · {r.id.slice(0, 8)}</option>
          ))}
        </select>
      </div>
      {!runId && <Empty title="No run selected" hint="Runs appear here after Models launches one." />}
      {runId && q.isLoading && <Loading what="targets" />}
      {runId && q.isError && <Err message={(q.error as Error).message} />}
      {q.data && q.data.items.length === 0 && <Empty title="No targets" hint="Lower the target percentile or check evidence coverage." />}
      {q.data && q.data.items.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="grid">
            <thead><tr><th>Rank</th><th>Mean</th><th>Max</th><th>Coverage</th><th>Area m²</th><th>Centroid (DD)</th><th>Status</th><th>Review</th><th /></tr></thead>
            <tbody>
              {q.data.items.map((t) => (
                <tr key={t.id}>
                  <td className="text-amber-300 font-bold">#{t.rank}</td>
                  <td>{t.mean_score.toFixed(3)}</td>
                  <td>{t.max_score.toFixed(3)}</td>
                  <td>{(t.coverage * 100).toFixed(0)}%</td>
                  <td>{t.area_m2.toLocaleString()}</td>
                  <td>{t.centroid_lat.toFixed(4)}, {t.centroid_lon.toFixed(4)}</td>
                  <td><Badge label={t.status_label} /></td>
                  <td>{t.review_status}</td>
                  <td><Link className="btn-ghost" to={`/targets/${t.id}`}>Dossier</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Page>
  );
}

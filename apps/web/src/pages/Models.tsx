import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, Dataset, Run } from '../api';
import { Badge, Empty, Loading, Err, Page } from '../components';
import { useUI } from '../store';

const DEFAULT_WEIGHTS = {
  dist_structure: 0.3, fault_density: 0.15, lineament_density: 0.1,
  lithology: 0.2, geochem_au: 0.15, alteration_iron_oxide: 0.05, alteration_clay: 0.05,
};

const REQUIRED_GROUPS: Record<string, string[]> = {
  Au: ['structure', 'host_lithology', 'alteration_or_geochem'],
  REE: ['radiometric_or_alkaline_lithology', 'structure'],
  C: ['radiometric_or_alkaline_lithology', 'structure'],
  Nb: ['radiometric_or_alkaline_lithology', 'structure'],
  Ti: ['host_lithology', 'structure'],
  U: ['structure', 'host_lithology', 'alteration_or_geochem'],
};

export default function Models() {
  const { projectId, setRun } = useUI();
  const [method, setMethod] = useState('weighted');
  const [weights, setWeights] = useState(DEFAULT_WEIGHTS);
  const [percentile, setPercentile] = useState(95);
  const [minArea, setMinArea] = useState(200000);
  const [mergeM, setMergeM] = useState(500);
  const [maxTargets, setMaxTargets] = useState(20);
  const [msg, setMsg] = useState('');
  const ds = useQuery({
    queryKey: ['datasets', projectId],
    queryFn: () => api.get<{ total: number; items: Dataset[] }>(`/datasets?project_id=${projectId}`),
    enabled: !!projectId,
  });
  const proj = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get<any>(`/projects/${projectId}`),
    enabled: !!projectId,
  });
  const runs = useQuery({
    queryKey: ['runs', projectId],
    queryFn: () => api.get<{ total: number; items: Run[] }>(`/runs?project_id=${projectId}`),
    enabled: !!projectId, refetchInterval: 3000,
  });
  if (!projectId) return <Page title="Models"><Empty title="No project selected" /></Page>;

  async function launch() {
    setMsg('');
    try {
      const r = await api.post<{ id: string }>(`/runs?project_id=${projectId}`, {
        method, config: {
          grid_m: 200, weights,
          target_percentile: percentile, target_min_area_m2: minArea,
          target_merge_distance_m: mergeM, target_max_targets: maxTargets,
        }, seed: 42,
      });
      setRun(r.id);
      setMsg(`Run queued: ${r.id}`);
      runs.refetch();
    } catch (e: any) { setMsg(`Error: ${e.message}`); }
  }

  const sum = Object.values(weights).reduce((a, b) => a + b, 0);
  const commodity = proj.data?.commodity ?? 'Au';
  const required = REQUIRED_GROUPS[commodity] ?? REQUIRED_GROUPS.Au;
  const lastDone = runs.data?.items.find((r) => r.status === 'done');
  const gate = (lastDone?.metrics as any)?.evidence_gate;

  return (
    <Page title="Mineral-system models" sub="Gold (orogenic) and REE (carbonatite) templates are DRAFT — require geologist review. Weights renormalise automatically.">
      {ds.isLoading && <Loading what="datasets" />}
      {ds.isError && <Err message={(ds.error as Error).message} />}
      <div className="card">
        <div className="font-medium">Evidence available: {(ds.data?.items.length ?? 0)} datasets</div>
        <div className="font-mono text-xs text-neutral-400">{(ds.data?.items ?? []).map((d) => `${d.kind}:${d.feature_count}`).join(' · ')}</div>
        <div className="text-xs mt-2">Commodity <span className="font-mono">{commodity}</span> requires evidence groups: <span className="font-mono text-amber-300">{required.join(' · ')}</span></div>
        {proj.data?.status_label && <div className="mt-1 flex gap-2 items-center text-xs">Project badge: <Badge label={proj.data.status_label} /></div>}
      </div>
      {gate && (
        <div className={`card text-sm ${gate.sufficient ? 'border-emerald-800' : 'border-orange-700'}`}>
          <div className="font-medium">{gate.sufficient ? 'Evidence sufficient — targets will be ranked.' : 'INSUFFICIENT EVIDENCE — not a targeting result.'}</div>
          <div className="font-mono text-xs text-neutral-400 mt-1">
            present: {Object.keys(gate.present_groups ?? {}).join(', ') || '—'} · missing: {(gate.missing_groups ?? []).join(', ') || '—'}
          </div>
        </div>
      )}
      <div className="card space-y-3">
        <div className="flex gap-2 items-center">
          <span className="label">Method</span>
          <select className="input max-w-xs" value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="weighted">Weighted overlay (baseline, transparent)</option>
            <option value="fuzzy">Fuzzy logic (gamma)</option>
            <option value="wofe">Weights of evidence (needs ≥10 occurrences)</option>
            <option value="logreg">Logistic regression (needs ≥10 occurrences)</option>
          </select>
        </div>
        {Object.entries(weights).map(([k, v]) => (
          <div key={k} className="flex items-center gap-2">
            <span className="font-mono text-xs w-40">{k}</span>
            <input type="range" min={0} max={1} step={0.05} value={v} className="flex-1"
              onChange={(e) => setWeights({ ...weights, [k]: parseFloat(e.target.value) })} />
            <span className="font-mono text-xs w-12">{v.toFixed(2)}</span>
          </div>
        ))}
        <div className="text-xs text-neutral-400">Weights sum {sum.toFixed(2)} (renormalised at run time; absent layers excluded, not zeroed).</div>
        <div className="grid md:grid-cols-4 gap-2">
          <label className="text-xs">Top % threshold<input className="input" type="number" min={80} max={99.9} step={0.5} value={percentile} onChange={(e) => setPercentile(parseFloat(e.target.value))} /></label>
          <label className="text-xs">Min area m²<input className="input" type="number" min={10000} step={10000} value={minArea} onChange={(e) => setMinArea(parseFloat(e.target.value))} /></label>
          <label className="text-xs">Merge distance m<input className="input" type="number" min={0} step={100} value={mergeM} onChange={(e) => setMergeM(parseFloat(e.target.value))} /></label>
          <label className="text-xs">Max targets<input className="input" type="number" min={1} max={100} value={maxTargets} onChange={(e) => setMaxTargets(parseInt(e.target.value))} /></label>
        </div>
        <div className="text-xs text-neutral-400">Defaults (top 5% · 200 000 m² · 500 m merge · max 20) target ~5–20 pilot targets; loosen only with justification.</div>
        <button className="btn" onClick={launch}>Run analysis (background job)</button>
        {msg && <div className="text-sm">{msg}</div>}
      </div>
      <div className="card">
        <div className="font-medium mb-1">Run history</div>
        {runs.data?.items.map((r) => (
          <div key={r.id} className="font-mono text-xs py-1 border-b border-neutral-800 flex gap-2 items-center flex-wrap">
            <span>{r.id.slice(0, 8)}</span><span>{r.method}</span><span>{r.status}</span>
            <span>{(r.progress * 100).toFixed(0)}%</span>
            {(r.metrics as any)?.evidence_gate && (
              <span className={(r.metrics as any).evidence_gate.sufficient ? 'text-emerald-300' : 'text-orange-300'}>
                {(r.metrics as any).evidence_gate.sufficient ? 'sufficient' : 'insufficient evidence'}
              </span>
            )}
            <button className="btn-ghost" onClick={() => setRun(r.id)}>Select</button>
          </div>
        )) ?? <span className="text-neutral-500 text-sm">No runs yet.</span>}
      </div>
    </Page>
  );
}

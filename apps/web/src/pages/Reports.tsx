import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, apiUrl } from '../api';
import { Empty, Loading, Err, Page } from '../components';
import { useUI } from '../store';

export default function Reports() {
  const { projectId, runId } = useUI();
  const [cmp, setCmp] = useState<any>(null);
  const sum = useQuery({
    queryKey: ['summary', projectId],
    queryFn: () => api.get<any>(`/projects/${projectId}/summary`),
    enabled: !!projectId,
  });
  if (!projectId) return <Page title="Reports"><Empty title="No project selected" /></Page>;

  async function compare() {
    const ids = prompt('Two run IDs, comma-separated (swipe-compare):');
    if (!ids) return;
    try { setCmp(await api.get(`/runs/compare?ids=${encodeURIComponent(ids)}`)); }
    catch (e: any) { setCmp({ error: e.message }); }
  }

  return (
    <Page title="Reports & exports" sub="Dossiers and project summaries — every number computed from stored data.">
      {sum.isLoading && <Loading what="summary" />}
      {sum.isError && <Err message={(sum.error as Error).message} />}
      {sum.data && (
        <div className="card">
          <div className="font-medium">{sum.data.project.name} — {sum.data.project.commodity}</div>
          <div className="font-mono text-xs text-neutral-400 mt-1">
            {sum.data.counts.datasets} datasets · {sum.data.counts.runs} runs · {sum.data.counts.targets} targets (latest run)
          </div>
          <pre className="font-mono text-xs bg-black/40 rounded p-2 mt-2 overflow-x-auto max-h-64">{JSON.stringify(sum.data, null, 1)}</pre>
        </div>
      )}
      <div className="card space-y-2">
        <div className="font-medium">Exports (current run)</div>
        {!runId && <p className="text-sm text-neutral-500">Select a run on the Map screen first.</p>}
        {runId && (
          <div className="flex gap-2 flex-wrap">
            <a className="btn-ghost" href={apiUrl(`/runs/${runId}/export.geojson`)}>Targets GeoJSON</a>
            <a className="btn-ghost" href={apiUrl(`/runs/${runId}/export.csv`)}>Targets CSV</a>
            <a className="btn-ghost" href={apiUrl(`/runs/${runId}/export.kml`)}>Targets KML</a>
            <button className="btn-ghost" onClick={compare}>Compare two runs</button>
          </div>
        )}
        {cmp && <pre className="font-mono text-xs bg-black/40 rounded p-2 overflow-x-auto">{JSON.stringify(cmp, null, 1)}</pre>}
      </div>
    </Page>
  );
}

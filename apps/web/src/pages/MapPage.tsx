import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import MapView from '../MapView';
import { api, apiUrl, Dataset, Page as P, Run } from '../api';
import { Badge, Empty } from '../components';
import { useUI } from '../store';

/** Flagship screen: layer tree (left), map, inspector (right). */
export default function MapPage() {
  const { projectId, runId, mapState, setMap, layerVis, toggleLayer } = useUI();
  const [cursor, setCursor] = useState<{ lng: number; lat: number } | null>(null);
  const [picked, setPicked] = useState<any>(null);
  const [overlayIds, setOverlayIds] = useState<string[]>([]);
  const [demIds, setDemIds] = useState<string[]>([]);
  const [demCache, setDemCache] = useState<Record<string, { dataUrl: string; bounds: [number, number, number, number] }>>({});

  const ds = useQuery({
    queryKey: ['datasets', projectId],
    queryFn: () => api.get<{ total: number; items: Dataset[] }>(`/datasets?project_id=${projectId}`),
    enabled: !!projectId,
  });
  const runs = useQuery({
    queryKey: ['runs', projectId],
    queryFn: () => api.get<{ total: number; items: Run[] }>(`/runs?project_id=${projectId}`),
    enabled: !!projectId,
    refetchInterval: 3000,
  });

  const overlays = useMemo(
    () => (ds.data?.items ?? []).filter((d) => overlayIds.includes(d.id))
      .map((d) => ({ id: d.id, url: apiUrl(`/datasets/${d.id}/geojson`), kind: d.kind })),
    [ds.data, overlayIds],
  );

  async function toggleDem(d: Dataset) {
    if (demIds.includes(d.id)) {
      setDemIds((s) => s.filter((x) => x !== d.id));
      return;
    }
    setDemIds((s) => [...s, d.id]);
    if (!demCache[d.id]) {
      try {
        const j = await api.get<{ data_url: string; bounds: [number, number, number, number] }>(`/datasets/${d.id}/hillshade`);
        setDemCache((c) => ({ ...c, [d.id]: { dataUrl: j.data_url, bounds: j.bounds } }));
      } catch { /* toast-less honest failure: box unchecked state stays */ }
    }
  }
  const imageOverlays = useMemo(
    () => demIds.filter((id) => demCache[id]).map((id) => ({ id, ...demCache[id] })),
    [demIds, demCache],
  );

  if (!projectId) return <div className="p-4"><Empty title="No project selected" hint="Pick one on the Workspace page." /></div>;

  const groups: Record<string, Dataset[]> = {};
  for (const d of ds.data?.items ?? []) (groups[d.kind] ??= []).push(d);

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* left: layers */}
      <aside className="w-64 shrink-0 overflow-y-auto p-3 border-r border-neutral-800 space-y-2">
        <div className="label">Results</div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={!!layerVis.prospectivity} onChange={() => toggleLayer('prospectivity')} />
          Prospectivity surface
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={!!layerVis.targets} onChange={() => toggleLayer('targets')} />
          Ranked targets
        </label>
        <div className="label pt-2">Run</div>
        <select className="input" value={runId ?? ''} onChange={(e) => useUI.getState().setRun(e.target.value || null)}>
          <option value="">— select run —</option>
          {runs.data?.items.map((r) => (
            <option key={r.id} value={r.id}>{r.method} · {r.status} · {r.id.slice(0, 6)}</option>
          ))}
        </select>
        <div className="label pt-2">Evidence layers</div>
        {Object.entries(groups).map(([kind, items]) => (
          <div key={kind}>
            <div className="text-xs font-medium text-neutral-300 capitalize">{kind}</div>
            {items.map((d) => (
              d.kind === 'dem' ? (
                <label key={d.id} className="flex items-start gap-2 text-xs py-0.5">
                  <input type="checkbox" className="mt-0.5" checked={demIds.includes(d.id)}
                    onChange={() => toggleDem(d)} />
                  <span>{d.name} (hillshade) <Badge label={d.status_label} /></span>
                </label>
              ) : (
                <label key={d.id} className="flex items-start gap-2 text-xs py-0.5">
                  <input type="checkbox" className="mt-0.5" checked={overlayIds.includes(d.id)}
                    onChange={() => setOverlayIds((s) => (s.includes(d.id) ? s.filter((x) => x !== d.id) : [...s, d.id]))} />
                  <span>{d.name} <Badge label={d.status_label} /></span>
                </label>
              )
            ))}
          </div>
        ))}
        <div className="label pt-2">Threshold</div>
        <input type="range" min={0} max={1} step={0.05} className="w-full"
          value={useUI.getState().threshold} onChange={(e) => useUI.getState().setThreshold(parseFloat(e.target.value))} />
      </aside>

      {/* map */}
      <div className="flex-1 relative p-2">
        <MapView lng={mapState.lng} lat={mapState.lat} zoom={mapState.zoom}
          onMove={(lng, lat, zoom) => setMap({ lng, lat, zoom })}
          onCursor={(lng, lat) => setCursor({ lng, lat })}
          onFeatureClick={setPicked}
          gridPointsUrl={runId && layerVis.prospectivity ? apiUrl(`/runs/${runId}/grid_points?stride=4`) : null}
          targetsUrl={runId && layerVis.targets ? apiUrl(`/targets?run_id=${runId}`) : null}
          overlays={overlays} imageOverlays={imageOverlays} cursor={cursor} />
        <div className="absolute bottom-4 left-4 font-mono text-[11px] bg-black/70 px-2 py-1 rounded">
          {cursor ? `${cursor.lat.toFixed(5)}, ${cursor.lng.toFixed(5)}` : 'move cursor for coordinates'} · share URL copies view
        </div>
      </div>

      {/* right: inspector */}
      <aside className="w-72 shrink-0 overflow-y-auto p-3 border-l border-neutral-800">
        <div className="label">Inspector</div>
        {picked ? (
          <div className="card mt-2">
            <pre className="font-mono text-xs whitespace-pre-wrap">{JSON.stringify(picked.properties ?? picked, null, 1)}</pre>
            {picked.properties?.id && (
              <Link className="btn-ghost mt-2 inline-block" to={`/targets/${picked.properties.id}`}>Open dossier</Link>
            )}
            <button className="btn-ghost mt-2 ml-2" onClick={() => setPicked(null)}>Clear</button>
          </div>
        ) : (
          <p className="text-neutral-500 text-sm mt-2">Click any feature — attributes, source and status appear here.</p>
        )}
        {runId && <RunCard runId={runId} />}
      </aside>
    </div>
  );
}

function RunCard({ runId }: { runId: string }) {
  const q = useQuery({ queryKey: ['run', runId], queryFn: () => api.get<Run>(`/runs/${runId}`), refetchInterval: 3000 });
  const r = q.data;
  if (!r) return null;
  const m = r.metrics ?? {};
  return (
    <div className="card mt-3">
      <div className="text-sm font-medium">Run {r.id.slice(0, 8)} · {r.method}</div>
      <div className="text-xs text-neutral-400">{r.status} · {(r.progress * 100).toFixed(0)}%</div>
      {r.status === 'running' && <div className="h-1.5 bg-neutral-800 rounded mt-1"><div className="h-1.5 bg-amber-500 rounded" style={{ width: `${r.progress * 100}%` }} /></div>}
      {r.status === 'done' && (
        <div className="font-mono text-xs mt-1">
          targets: {r.grid_meta?.n_targets ?? '?'} · mean {m.score_stats?.mean?.toFixed(3)} · coverage {((m.coverage_mean ?? 0) * 100).toFixed(0)}%
        </div>
      )}
      {r.status === 'done' && (m as any).evidence_gate && !(m as any).evidence_gate.sufficient && (
        <div className="text-orange-300 text-xs mt-1">INSUFFICIENT EVIDENCE — surface for inspection only; missing: {((m as any).evidence_gate.missing_groups ?? []).join(', ')}</div>
      )}
      {r.status === 'failed' && <div className="text-red-300 text-xs mt-1">{r.error.slice(0, 300)}</div>}
      <Badge label="MODEL OUTPUT" />
    </div>
  );
}

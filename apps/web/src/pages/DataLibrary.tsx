import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, Dataset } from '../api';
import { Badge, Empty, Loading, Err, Page } from '../components';
import { useUI } from '../store';

export default function DataLibrary() {
  const { projectId } = useUI();
  const [kind, setKind] = useState('');
  const q = useQuery({
    queryKey: ['datasets', projectId, kind],
    queryFn: () => api.get<{ total: number; items: Dataset[] }>(
      `/datasets?${projectId ? `project_id=${projectId}&` : ''}${kind ? `kind=${kind}` : ''}`),
  });
  const [open, setOpen] = useState<string | null>(null);

  return (
    <Page title="Data Library" sub="Registry, metadata, quality reports and provenance. Badges tell real / synthetic / derived apart.">
      <div className="flex gap-2">
        <select className="input max-w-xs" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All kinds</option>
          {['geology', 'structure', 'geophysics', 'geochem', 'remotesensing', 'occurrences', 'constraints', 'dem', 'report'].map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </div>
      {q.isLoading && <Loading what="datasets" />}
      {q.isError && <Err message={(q.error as Error).message} />}
      {q.data && q.data.items.length === 0 && <Empty title="No datasets" hint="Import one on the Ingest page." />}
      {q.data?.items.map((d) => (
        <div key={d.id} className="card">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium">{d.name}</span>
            <Badge label={d.status_label} />
            {(d as any).restricted && <Badge label="RESTRICTED — local only" />}
            <span className="font-mono text-xs text-neutral-500">{d.kind} · {d.format} · {d.feature_count} features</span>
          </div>
          <div className="text-xs text-neutral-400 mt-1">Licence: {d.licence || '—'} · Source: {d.source_url || '—'}</div>
          {(d.provenance as any)?.citation_text && (
            <div className="text-xs text-neutral-300 mt-1">Citation: {(d.provenance as any).citation_text}</div>
          )}
          <button className="btn-ghost mt-2" onClick={() => setOpen(open === d.id ? null : d.id)}>
            {open === d.id ? 'Hide quality report' : 'Quality + provenance report'}
          </button>
          {open === d.id && (
            <pre className="font-mono text-xs bg-black/40 rounded p-2 mt-2 overflow-x-auto">
              {JSON.stringify({ quality: d.quality, provenance: d.provenance }, null, 1)}
            </pre>
          )}
        </div>
      ))}
    </Page>
  );
}

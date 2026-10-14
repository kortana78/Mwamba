import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, Project } from '../api';
import { Badge, Empty, Loading, Err, Page } from '../components';
import { COMMODITIES } from '../constants';
import { useUI } from '../store';
import AoiPicker from '../AoiPicker';

export default function Home() {
  const { projectId, setProject } = useUI();
  const q = useQuery({ queryKey: ['projects'], queryFn: () => api.get<{ total: number; items: Project[] }>('/projects') });

  return (
    <Page title="Workspace" sub="Each project = commodity + area of interest + datasets + analysis runs. Status derives from its datasets.">
      {q.isLoading && <Loading what="projects" />}
      {q.isError && <Err message={(q.error as Error).message} />}
      {q.data && q.data.items.length === 0 && <Empty title="No projects yet" hint="Create one below to start." />}
      <div className="grid md:grid-cols-2 gap-3">
        {q.data?.items.map((p) => (
          <button key={p.id} onClick={() => setProject(p.id)}
            className={`card text-left hover:border-amber-500/60 ${projectId === p.id ? 'border-amber-500' : ''}`}>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium">{p.name}</span>
              <Badge label={p.status_label} />
            </div>
            <div className="font-mono text-xs text-neutral-400 mt-1">
              {p.commodity} – {COMMODITIES[p.commodity] ?? ''} · grid {p.grid_m} m · {p.n_datasets ?? '?'} datasets
            </div>
            <div className="mt-2 flex gap-2">
              <Link to={`/map?project=${p.id}`} className="btn-ghost" onClick={(e) => e.stopPropagation()}>Open map</Link>
              <Link to={`/models?project=${p.id}`} className="btn-ghost" onClick={(e) => e.stopPropagation()}>Models</Link>
            </div>
          </button>
        ))}
      </div>
      <NewProject onDone={() => q.refetch()} />
    </Page>
  );
}

type Tab = 'draw' | 'district' | 'upload' | 'advanced';

function NewProject({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('');
  const [commodity, setCommodity] = useState('Au');
  const [tab, setTab] = useState<Tab>('draw');
  const [aoi, setAoi] = useState<any>(null);
  const [aoiErr, setAoiErr] = useState('');
  const [paste, setPaste] = useState('');
  const [districts, setDistricts] = useState<any[] | null>(null);
  const [district, setDistrict] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const valid = name.trim().length > 0 && aoi && !aoiErr;

  async function loadDistricts() {
    if (districts) return;
    try {
      const r = await fetch('/districts.json');
      if (!r.ok) throw new Error('not available');
      const j = await r.json();
      setDistricts(j.features);
    } catch {
      setAoiErr('District boundaries not bundled in this build.');
    }
  }

  async function pickDistrict(nm: string) {
    setDistrict(nm);
    const f = districts?.find((d) => d.properties.name === nm);
    if (!f) { setAoi(null); return; }
    const g = f.geometry;
    if (g.type !== 'Polygon' && g.type !== 'MultiPolygon') { setAoiErr('District geometry unusable.'); return; }
    setAoiErr('');
    setAoi(g.type === 'Polygon' ? g : largestPoly(g));
  }

  async function uploadAoi() {
    if (!file) return;
    setErr(''); setAoiErr('');
    const form = new FormData();
    form.append('file', file);
    try {
      const j = await api.postForm<{ aoi_geojson: any }>('/projects/parse-aoi', form);
      setAoi(j.aoi_geojson);
    } catch (e: any) { setAoiErr(e.message); }
  }

  function applyPaste() {
    try {
      const o = JSON.parse(paste);
      const g = o.type === 'Feature' ? o.geometry : o;
      if (!g || (g.type !== 'Polygon' && g.type !== 'MultiPolygon')) throw new Error('not a polygon');
      setAoiErr('');
      setAoi(g);
    } catch (e: any) { setAoiErr(`Invalid GeoJSON: ${e.message}`); }
  }

  async function create() {
    if (!valid || busy) return;
    setBusy(true); setErr('');
    try {
      const r = await api.post<{ id: string }>('/projects', { name: name.trim(), commodity, aoi_geojson: aoi, grid_m: 200 });
      useUI.getState().setProject(r.id);
      setName(''); setAoi(null); setPaste(''); setFile(null);
      onDone();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="card space-y-3">
      <div className="font-medium">New project</div>
      <div className="grid md:grid-cols-2 gap-2">
        <div><div className="label">Name *</div><input className="input" placeholder="e.g. Chitipa Gold" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div><div className="label">Commodity *</div>
          <select className="input" value={commodity} onChange={(e) => setCommodity(e.target.value)}>
            {Object.entries(COMMODITIES).map(([code, full]) => <option key={code} value={code}>{code} – {full}</option>)}
          </select>
        </div>
      </div>
      <div className="label">Area of interest * (must lie inside Malawi)</div>
      <div className="flex gap-2 flex-wrap">
        {(['draw', 'district', 'upload', 'advanced'] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? 'btn' : 'btn-ghost'} onClick={() => { setTab(t); if (t === 'district') loadDistricts(); }}>
            {t === 'draw' ? 'Draw' : t === 'district' ? 'District' : t === 'upload' ? 'Upload' : 'Advanced'}
          </button>
        ))}
      </div>
      {tab === 'draw' && <AoiPicker onAoi={(p, e) => { setAoi(p); setAoiErr(e); }} />}
      {tab === 'district' && (
        districts ? (
          <select className="input max-w-xs" value={district} onChange={(e) => pickDistrict(e.target.value)}>
            <option value="">— choose district —</option>
            {districts.map((d) => <option key={d.properties.name} value={d.properties.name}>{d.properties.name}</option>)}
          </select>
        ) : <div className="text-sm text-neutral-400">Loading districts…</div>
      )}
      {tab === 'upload' && (
        <div className="flex gap-2 items-center flex-wrap">
          <input type="file" accept=".geojson,.json,.kml,.xml" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <button className="btn-ghost" disabled={!file} onClick={uploadAoi}>Validate upload</button>
        </div>
      )}
      {tab === 'advanced' && (
        <div>
          <textarea className="input font-mono" rows={3} placeholder='{"type":"Polygon","coordinates":[…]}' value={paste} onChange={(e) => setPaste(e.target.value)} />
          <button className="btn-ghost mt-1" onClick={applyPaste}>Use pasted GeoJSON</button>
        </div>
      )}
      {aoiErr && <div className="text-red-300 text-sm">{aoiErr}</div>}
      {aoi && !aoiErr && <div className="text-emerald-300 text-sm">AOI ready ({aoi.type}).</div>}
      <div className="flex gap-2 items-center">
        <button className="btn bg-amber-500 hover:bg-amber-400 text-black font-semibold px-6" disabled={!valid || busy} onClick={create}>
          {busy ? 'Creating…' : 'Create project'}
        </button>
        {!valid && <span className="text-xs text-neutral-500">Name + valid AOI required.</span>}
      </div>
      {err && <div className="text-red-300 text-sm">{err}</div>}
    </div>
  );
}

function largestPoly(g: any) {
  let best: any = null; let bestLen = -1;
  for (const poly of g.coordinates) {
    const n = JSON.stringify(poly).length;
    if (n > bestLen) { bestLen = n; best = poly; }
  }
  return { type: 'Polygon', coordinates: best };
}

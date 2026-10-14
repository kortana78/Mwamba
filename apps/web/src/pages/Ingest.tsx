import { useState } from 'react';
import { api } from '../api';
import { Page } from '../components';
import { useUI } from '../store';

const KINDS = ['geology', 'structure', 'geophysics', 'geochem', 'remotesensing', 'occurrences', 'constraints', 'dem', 'report'];
const TABS = ['geojson', 'csv', 'shapefile', 'geopackage', 'kml', 'geotiff', 'sentinel2', 'cited', 'validate', 'report'] as const;

export default function Ingest() {
  const { projectId } = useUI();
  const [tab, setTab] = useState<(typeof TABS)[number]>('geojson');
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [kind, setKind] = useState('occurrences');
  const [crs, setCrs] = useState('auto');
  const [layer, setLayer] = useState('');
  const [restricted, setRestricted] = useState(false);
  const [out, setOut] = useState('');
  const [busy, setBusy] = useState(false);
  // cited-occurrence form
  const [cited, setCited] = useState({
    name: '', commodity: 'Au', x: '', y: '', crs_original: 'EPSG:4326',
    accuracy_m: '', author: '', year: '', title: '', page_figure: '', notes: '',
  });

  const acceptFor: Record<string, string> = {
    geojson: '.geojson,.json', csv: '.csv', shapefile: '.zip', geopackage: '.gpkg',
    kml: '.kml,.xml', geotiff: '.tif,.tiff,.cog', sentinel2: '.tif,.tiff',
    cited: '', validate: '.geojson,.json,.csv', report: '.pdf',
  };

  async function send(validateOnly: boolean) {
    if (!file) { setOut('Pick a file first.'); return; }
    setBusy(true); setOut('');
    const common = (form: FormData) => {
      form.append('name', name || file!.name); form.append('kind', kind);
      if (projectId) form.append('project_id', projectId);
      form.append('file', file!);
    };
    try {
      let url = '';
      const form = new FormData();
      if (tab === 'csv') { common(form); url = '/ingest/csv'; }
      else if (tab === 'shapefile') { common(form); form.append('crs_original', crs); form.append('restricted', String(restricted)); url = '/ingest/shapefile'; }
      else if (tab === 'geopackage') {
        common(form); if (layer) form.append('layer', layer); url = '/ingest/geopackage';
      }
      else if (tab === 'kml') { common(form); url = '/ingest/kml'; }
      else if (tab === 'geotiff') { common(form); form.append('restricted', String(restricted)); url = '/ingest/geotiff'; }
      else if (tab === 'sentinel2') {
        form.append('name', name || file!.name);
        if (projectId) form.append('project_id', projectId);
        form.append('file', file!); url = '/ingest/sentinel2';
      }
      else if (tab === 'report') { form.append('file', file); url = '/documents/upload'; }
      else if (validateOnly || tab === 'validate') { form.append('file', file); url = '/ingest/validate-only'; }
      else { common(form); form.append('crs_original', crs); url = '/ingest/geojson'; }
      setOut(JSON.stringify(await api.postForm(url, form), null, 1));
    } catch (e: any) { setOut(`FAILED:\n${e.message}`); } finally { setBusy(false); }
  }

  async function sendCited() {
    setBusy(true); setOut('');
    try {
      const body = {
        name: cited.name, commodity: cited.commodity,
        project_id: projectId ?? null,
        x: parseFloat(cited.x), y: parseFloat(cited.y), crs_original: cited.crs_original,
        accuracy_m: cited.accuracy_m ? parseFloat(cited.accuracy_m) : null,
        citation: {
          author: cited.author, year: cited.year ? parseInt(cited.year) : null,
          title: cited.title, page_figure: cited.page_figure,
        },
        notes: cited.notes,
      };
      setOut(JSON.stringify(await api.post('/ingest/cited-occurrence', body), null, 1));
    } catch (e: any) { setOut(`FAILED:\n${e.message}`); } finally { setBusy(false); }
  }

  async function listLayers() {
    if (!file) { setOut('Pick a .gpkg file first.'); return; }
    const form = new FormData();
    form.append('file', file);
    try { setOut(JSON.stringify(await api.postForm('/ingest/geopackage/layers', form), null, 1)); }
    catch (e: any) { setOut(`FAILED:\n${e.message}`); }
  }

  const setC = (k: string, v: string) => setCited({ ...cited, [k]: v });

  return (
    <Page title="Ingest" sub="Upload → CRS declared or auto-detected (Malawi UTM36S frames supported) → validate → quality report → confirm.">
      <div className="flex gap-2 flex-wrap">
        {TABS.map((t) => (
          <button key={t} className={tab === t ? 'btn' : 'btn-ghost'} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === 'cited' ? (
        <div className="card space-y-2">
          <div className="text-sm text-neutral-300">Cited occurrence (literature record). VERIFIED only with author + year + title; otherwise stored UNVERIFIED.</div>
          <div className="grid md:grid-cols-3 gap-2">
            <input className="input" placeholder="Occurrence name" value={cited.name} onChange={(e) => setC('name', e.target.value)} />
            <select className="input" value={cited.commodity} onChange={(e) => setC('commodity', e.target.value)}>
              {['Au', 'C', 'REE', 'Nb', 'Ti', 'U'].map((c) => <option key={c}>{c}</option>)}
            </select>
            <select className="input" value={cited.crs_original} onChange={(e) => setC('crs_original', e.target.value)}>
              {['EPSG:4326', 'EPSG:32736', 'EPSG:20936', 'EPSG:4209'].map((c) => <option key={c}>{c}</option>)}
            </select>
            <input className="input" placeholder="X (lon or easting)" value={cited.x} onChange={(e) => setC('x', e.target.value)} />
            <input className="input" placeholder="Y (lat or northing)" value={cited.y} onChange={(e) => setC('y', e.target.value)} />
            <input className="input" placeholder="Accuracy (m, optional)" value={cited.accuracy_m} onChange={(e) => setC('accuracy_m', e.target.value)} />
            <input className="input" placeholder="Author (required for VERIFIED)" value={cited.author} onChange={(e) => setC('author', e.target.value)} />
            <input className="input" placeholder="Year (required)" value={cited.year} onChange={(e) => setC('year', e.target.value)} />
            <input className="input" placeholder="Title (required)" value={cited.title} onChange={(e) => setC('title', e.target.value)} />
            <input className="input" placeholder="Page / figure (optional)" value={cited.page_figure} onChange={(e) => setC('page_figure', e.target.value)} />
            <input className="input md:col-span-2" placeholder="Notes (optional)" value={cited.notes} onChange={(e) => setC('notes', e.target.value)} />
          </div>
          <button className="btn" disabled={busy} onClick={sendCited}>{busy ? 'Working…' : 'Save cited occurrence'}</button>
          {out && <pre className="font-mono text-xs bg-black/40 rounded p-2 overflow-x-auto max-h-96">{out}</pre>}
        </div>
      ) : (
        <div className="card space-y-2">
          <input type="file" accept={acceptFor[tab]} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          {!['validate', 'report'].includes(tab) && (
            <div className="grid md:grid-cols-4 gap-2">
              <input className="input" placeholder="Dataset name" value={name} onChange={(e) => setName(e.target.value)} />
              {tab !== 'sentinel2' && (
                <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
                  {KINDS.map((k) => <option key={k}>{k}</option>)}
                </select>
              )}
              {['geojson', 'csv', 'shapefile'].includes(tab) && (
                <select className="input" value={crs} onChange={(e) => setCrs(e.target.value)} title="Coordinate reference system">
                  <option value="auto">CRS: auto-detect</option>
                  {['EPSG:4326', 'EPSG:32736', 'EPSG:20936', 'EPSG:4209'].map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              )}
              {tab === 'geopackage' && (
                <div className="flex gap-1">
                  <input className="input" placeholder="layer (optional)" value={layer} onChange={(e) => setLayer(e.target.value)} />
                  <button className="btn-ghost" onClick={listLayers}>List</button>
                </div>
              )}
              {['shapefile', 'geotiff'].includes(tab) && (
                <label className="text-xs flex items-center gap-2">
                  <input type="checkbox" checked={restricted} onChange={(e) => setRestricted(e.target.checked)} />
                  Restricted (WDPA: local-only, no export)
                </label>
              )}
            </div>
          )}
          {tab === 'shapefile' && <p className="text-xs text-neutral-400">Zipped shapefile, one .shp layer per zip. Arc 1950 / UTM 36S auto-detected with logged transform. Tick Restricted for WDPA.</p>}
          {tab === 'geotiff' && <p className="text-xs text-neutral-400">GeoTIFF/COG (DEM, geophysics, remote sensing). CRS, nodata, resolution and Malawi extent validated.</p>}
          {tab === 'sentinel2' && <p className="text-xs text-neutral-400">Stacked multiband Sentinel-2 GeoTIFF (B2,B4,B8,B11,B12) → DERIVED iron-oxide (B4/B2) + clay (B11/B12) + NDVI, vegetation-masked. See docs/manual-data-download.md.</p>}
          {tab === 'report' && <p className="text-xs text-neutral-400">PDF reports → text + candidate coordinates → REVIEW QUEUE (never straight to analysis).</p>}
          <div className="flex gap-2">
            {!['report', 'geotiff', 'sentinel2'].includes(tab) && <button className="btn-ghost" disabled={busy} onClick={() => send(true)}>Validate only</button>}
            <button className="btn" disabled={busy || !file} onClick={() => send(false)}>{busy ? 'Working…' : tab === 'report' ? 'Upload report' : 'Validate + import'}</button>
          </div>
          {out && <pre className="font-mono text-xs bg-black/40 rounded p-2 overflow-x-auto max-h-96">{out}</pre>}
        </div>
      )}
    </Page>
  );
}

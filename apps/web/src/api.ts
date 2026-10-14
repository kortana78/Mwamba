/** Typed API client. In dev (no VITE_API_URL) calls go through the Vite
 *  `/api` proxy to the backend; in production VITE_API_URL points at the API. */
const _RAW_BASE = (import.meta as any).env?.VITE_API_URL ?? '';
// Render Blueprint injects a bare host (no scheme) via fromService; accept it.
const BASE = !_RAW_BASE ? '' : /^https?:\/\//i.test(_RAW_BASE) ? _RAW_BASE.replace(/\/$/, '') : `https://${_RAW_BASE.replace(/\/$/, '')}`;

/** Build a backend URL for any caller (fetch, <a href>, map sources). */
export function apiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`;
  if (BASE) return `${BASE}${p}`;
  return `/api${p.replace(/^\/api/, '')}`;
}

export function token(): string | null {
  return localStorage.getItem('mwamba_token');
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as any) };
  const t = token();
  if (t) headers['Authorization'] = `Bearer ${t}`;
  if (init.body && typeof init.body === 'string' && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  let r: Response;
  try {
    r = await fetch(apiUrl(path), { ...init, headers });
  } catch {
    // Render free tier sleeps: fetch itself fails while the server wakes.
    throw new Error('Waking the server — up to a minute. Please wait and retry.');
  }
  if (r.status === 401) {
    localStorage.removeItem('mwamba_token');
    if (window.location.pathname !== '/login') window.location.href = '/login';
    throw new Error('Not authenticated');
  }
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j);
    } catch { /* keep default */ }
    throw new Error(detail);
  }
  const ct = r.headers.get('content-type') ?? '';
  if (ct.includes('application/json') || ct.includes('geo+json')) return (await r.json()) as T;
  return (await r.text()) as unknown as T;
}

export const api = {
  get: <T>(p: string) => req<T>(p),
  post: <T>(p: string, body?: any) =>
    req<T>(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(p: string, body?: any) =>
    req<T>(p, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
  postForm: <T>(p: string, form: FormData) => req<T>(p, { method: 'POST', body: form as any }),
};

export interface Page<T> { total: number; items: T[]; }
export interface Project { id: string; name: string; commodity: string; commodity_name?: string; aoi_geojson: any; grid_m: number; status_label: string; n_datasets?: number; }
export interface Dataset { id: string; name: string; kind: string; format: string; status_label: string; feature_count: number; project_id: string | null; quality: any; licence: string; source_url: string; provenance: any; restricted?: boolean; }
export interface Run { id: string; project_id: string; method: string; status: string; progress: number; error: string; grid_meta: any; metrics: any; }
export interface Target { id: string; run_id: string; rank: number; area_m2: number; centroid_lon: number; centroid_lat: number; centroid_easting: number; centroid_northing: number; mean_score: number; max_score: number; coverage: number; status_label: string; review_status: string; reviewer: string; review_notes: string; evidence: any; polygon_geojson: any; }

export function csvDownload(filename: string, text: string) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

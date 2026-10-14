import { create } from 'zustand';

interface UI {
  projectId: string | null;
  runId: string | null;
  mapState: { lng: number; lat: number; zoom: number };
  layerVis: Record<string, boolean>;
  threshold: number;
  setProject: (id: string | null) => void;
  setRun: (id: string | null) => void;
  setMap: (m: Partial<UI['mapState']>) => void;
  toggleLayer: (k: string) => void;
  setThreshold: (v: number) => void;
}

/** URL encodes map state so views can be shared (acceptance #5-map). */
function fromURL() {
  const q = new URLSearchParams(window.location.search);
  return {
    lng: parseFloat(q.get('lng') ?? '33.3') || 33.3,
    lat: parseFloat(q.get('lat') ?? '-9.76') || -9.76,
    zoom: parseFloat(q.get('z') ?? '10') || 10,
  };
}

export const useUI = create<UI>((set) => ({
  projectId: localStorage.getItem('mwamba_project') ?? null,
  runId: localStorage.getItem('mwamba_run') ?? null,
  mapState: fromURL(),
  layerVis: { prospectivity: true, targets: true, occurrences: true, structures: true, geology: true, geochem: true },
  threshold: 0,
  setProject: (id) => {
    if (id) localStorage.setItem('mwamba_project', id); else localStorage.removeItem('mwamba_project');
    set({ projectId: id });
  },
  setRun: (id) => {
    if (id) localStorage.setItem('mwamba_run', id); else localStorage.removeItem('mwamba_run');
    set({ runId: id });
  },
  setMap: (m) =>
    set((s) => {
      const mapState = { ...s.mapState, ...m };
      const q = new URLSearchParams(window.location.search);
      q.set('lng', mapState.lng.toFixed(4)); q.set('lat', mapState.lat.toFixed(4)); q.set('z', String(mapState.zoom.toFixed(1)));
      window.history.replaceState(null, '', `${window.location.pathname}?${q}`);
      return { mapState };
    }),
  toggleLayer: (k) => set((s) => ({ layerVis: { ...s.layerVis, [k]: !s.layerVis[k] } })),
  setThreshold: (v) => set({ threshold: v }),
}));

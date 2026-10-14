import { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';

export interface MapViewProps {
  lng: number; lat: number; zoom: number;
  onMove?: (lng: number, lat: number, zoom: number) => void;
  gridPointsUrl?: string | null;
  targetsUrl?: string | null;
  overlays?: { id: string; url: string; kind: string }[];
  imageOverlays?: { id: string; dataUrl: string; bounds: [number, number, number, number] }[];
  onFeatureClick?: (info: any) => void;
  cursor?: { lng: number; lat: number } | null;
  onCursor?: (lng: number, lat: number) => void;
}

/** Flagship map: free OSM raster tiles (attributed), viridis prospectivity
 *  points, ranked target polygons, dataset overlays, cursor readout. */
export default function MapView(props: MapViewProps) {
  const divRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const propsRef = useRef(props);
  propsRef.current = props;

  useEffect(() => {
    if (!divRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: divRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors',
          },
        },
        layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
      },
      center: [propsRef.current.lng, propsRef.current.lat],
      zoom: propsRef.current.zoom,
    });
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.addControl(new maplibregl.ScaleControl(), 'bottom-left');
    map.on('moveend', () => {
      const c = map.getCenter();
      propsRef.current.onMove?.(+c.lng.toFixed(4), +c.lat.toFixed(4), +map.getZoom().toFixed(1));
    });
    map.on('mousemove', (e) => propsRef.current.onCursor?.(+e.lngLat.lng.toFixed(5), +e.lngLat.lat.toFixed(5)));
    map.on('click', (e) => {
      const feats = map.queryRenderedFeatures(e.point, { layers: ['mw-targets-fill', 'mw-grid', 'mw-overlay-points'] });
      if (feats.length) propsRef.current.onFeatureClick?.(feats[0]);
    });
    map.on('load', () => {
      // prospectivity points (viridis ramp by score)
      map.addSource('mw-grid', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({
        id: 'mw-grid', type: 'circle', source: 'mw-grid',
        paint: {
          'circle-radius': 3,
          'circle-opacity': 0.55,
          'circle-color': ['interpolate', ['linear'], ['get', 'score'], 0, '#440154', 0.25, '#3b528b', 0.5, '#21918c', 0.75, '#5ec962', 1, '#fde725'],
        },
      });
      map.addSource('mw-targets', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'mw-targets-fill', type: 'fill', source: 'mw-targets', paint: { 'fill-color': '#d9a441', 'fill-opacity': 0.25 } });
      map.addLayer({ id: 'mw-targets-line', type: 'line', source: 'mw-targets', paint: { 'line-color': '#d9a441', 'line-width': 2 } });
      map.addSource('mw-overlay', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'mw-overlay-points', type: 'circle', source: 'mw-overlay', paint: { 'circle-radius': 4, 'circle-color': '#7dd3fc', 'circle-stroke-color': '#0c4a6e', 'circle-stroke-width': 1 } });
      map.addLayer({ id: 'mw-overlay-lines', type: 'line', source: 'mw-overlay', paint: { 'line-color': '#f0abfc', 'line-width': 2 } });
      refresh(map, propsRef.current);
    });
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // refresh on prop change
  useEffect(() => {
    const map = mapRef.current;
    if (map && map.isStyleLoaded()) refresh(map, props);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.gridPointsUrl, props.targetsUrl, props.overlays, props.imageOverlays, props.cursor]);

  return <div ref={divRef} className="w-full h-full min-h-[60vh] rounded-lg overflow-hidden border border-neutral-800" />;
}

async function refresh(map: maplibregl.Map, p: MapViewProps) {
  const set = (src: string, url: string | null | undefined, fallback = true) => {
    const s = map.getSource(src) as maplibregl.GeoJSONSource | undefined;
    if (!s) return;
    if (!url) { if (fallback) s.setData({ type: 'FeatureCollection', features: [] } as any); return; }
    fetch(url, { headers: authH() }).then((r) => (r.ok ? r.json() : null)).then((j) => { if (j) s.setData(j); }).catch(() => {});
  };
  set('mw-grid', p.gridPointsUrl);
  // targets: fetch list API -> build FC from polygon_geojson
  if (p.targetsUrl) {
    try {
      const r = await fetch(p.targetsUrl, { headers: authH() });
      if (r.ok) {
        const j = await r.json();
        const feats = (j.items ?? []).map((t: any) => ({
          type: 'Feature',
          geometry: t.polygon_geojson?.geometry ?? t.polygon_geojson,
          properties: { rank: t.rank, mean_score: t.mean_score, id: t.id },
        })).filter((f: any) => f.geometry);
        (map.getSource('mw-targets') as maplibregl.GeoJSONSource)?.setData({ type: 'FeatureCollection', features: feats } as any);
      }
    } catch { /* offline-safe */ }
  }
  // DEM / raster image overlays (hillshade PNG + bounds, no TiTiler needed)
  const want = new Set((p.imageOverlays ?? []).map((o) => `mw-img-${o.id}`));
  for (const o of p.imageOverlays ?? []) {
    const sid = `mw-img-${o.id}`;
    const lid = `${sid}-lyr`;
    const [w, s, e, n] = o.bounds;
    const coords: [[number, number], [number, number], [number, number], [number, number]] =
      [[w, n], [e, n], [e, s], [w, s]];
    const existing = map.getSource(sid) as maplibregl.ImageSource | undefined;
    if (existing && (existing as any)._dataUrl !== o.dataUrl) {
      map.removeLayer(lid);
      map.removeSource(sid);
    }
    if (!map.getSource(sid)) {
      map.addSource(sid, { type: 'image', url: o.dataUrl, coordinates: coords });
      (map.getSource(sid) as any)._dataUrl = o.dataUrl;
      map.addLayer({ id: lid, type: 'raster', source: sid, paint: { 'raster-opacity': 0.85 } }, 'mw-grid');
    }
  }
  // drop overlays no longer wanted
  const style = map.getStyle();
  for (const l of style.layers ?? []) {
    if (l.id.startsWith('mw-img-') && l.id.endsWith('-lyr') && !want.has(l.id.slice(0, -4))) {
      map.removeLayer(l.id);
      map.removeSource(l.id.slice(0, -4));
    }
  }
  // dataset overlays merged into one source
  const ov = map.getSource('mw-overlay') as maplibregl.GeoJSONSource | undefined;
  if (ov) {
    if (!p.overlays?.length) ov.setData({ type: 'FeatureCollection', features: [] } as any);
    else {
      const all: any[] = [];
      for (const o of p.overlays) {
        try {
          const r = await fetch(o.url, { headers: authH() });
          if (r.ok) { const j = await r.json(); all.push(...(j.features ?? [])); }
        } catch { /* skip */ }
      }
      ov.setData({ type: 'FeatureCollection', features: all } as any);
    }
  }
}

function authH(): Record<string, string> {
  const t = localStorage.getItem('mwamba_token');
  return t ? { Authorization: `Bearer ${t}` } : {};
}

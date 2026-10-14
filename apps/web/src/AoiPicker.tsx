import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';

/** Draw-a-rectangle AOI picker on a small map. Emits a GeoJSON Polygon. */
export default function AoiPicker({ onAoi }: { onAoi: (poly: any | null, err: string) => void }) {
  const divRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [hint, setHint] = useState('Drag a rectangle inside Malawi.');

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
      center: [33.9, -13.4],
      zoom: 5.5,
    });
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.on('load', () => {
      map.addSource('aoi', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'aoi-fill', type: 'fill', source: 'aoi', paint: { 'fill-color': '#d9a441', 'fill-opacity': 0.3 } });
      map.addLayer({ id: 'aoi-line', type: 'line', source: 'aoi', paint: { 'line-color': '#d9a441', 'line-width': 2 } });
    });

    let start: maplibregl.LngLat | null = null;
    const src = () => map.getSource('aoi') as maplibregl.GeoJSONSource | undefined;
    map.on('mousedown', (e) => {
      if ((e.originalEvent.target as HTMLElement).closest('.maplibregl-ctrl')) return;
      start = e.lngLat;
      map.dragPan.disable();
    });
    map.on('mousemove', (e) => {
      if (!start) return;
      const poly = boxPoly(start, e.lngLat);
      src()?.setData({ type: 'FeatureCollection', features: [{ type: 'Feature', geometry: poly, properties: {} }] } as any);
    });
    map.on('mouseup', (e) => {
      if (!start) return;
      map.dragPan.enable();
      const poly = boxPoly(start, e.lngLat);
      start = null;
      const ring = poly.coordinates[0] as number[][];
      const lons = ring.map((p) => p[0]);
      const lats = ring.map((p) => p[1]);
      const w = Math.min(...lons), ee = Math.max(...lons);
      const s = Math.min(...lats), n = Math.max(...lats);
      if (ee - w < 0.005 || n - s < 0.005) {
        onAoi(null, 'Box too small — drag a larger rectangle.');
        setHint('Box too small — drag a larger rectangle.');
        return;
      }
      if (ee < 32.6 || w > 35.9 || n < -17.2 || s > -9.3) {
        onAoi(null, 'Box falls outside Malawi — draw inside the country.');
        setHint('Box falls outside Malawi — draw inside the country.');
        src()?.setData({ type: 'FeatureCollection', features: [] } as any);
        return;
      }
      setHint(`AOI: ${w.toFixed(3)},${s.toFixed(3)} → ${ee.toFixed(3)},${n.toFixed(3)}`);
      onAoi({ type: 'Polygon', coordinates: [poly.coordinates[0]] }, '');
    });
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div ref={divRef} className="w-full h-64 rounded border border-neutral-700" style={{ cursor: 'crosshair' }} />
      <div className="text-xs text-neutral-400 mt-1">{hint}</div>
    </div>
  );
}

function boxPoly(a: maplibregl.LngLat, b: maplibregl.LngLat) {
  const ring = [[a.lng, a.lat], [b.lng, a.lat], [b.lng, b.lat], [a.lng, b.lat], [a.lng, a.lat]];
  return { type: 'Polygon', coordinates: [ring] };
}

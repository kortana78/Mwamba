export const COMMODITIES: Record<string, string> = {
  Au: 'Gold',
  C: 'Graphite',
  REE: 'Rare Earth Elements',
  Nb: 'Niobium',
  Ti: 'Rutile (Titanium)',
  U: 'Uranium',
};

export const DEMO_MODE = (import.meta as any).env?.VITE_DEMO_MODE === 'true';

import React from 'react';

export const STATUS_COLORS: Record<string, string> = {
  VERIFIED: 'bg-emerald-600/20 text-emerald-300 border-emerald-600/40',
  DERIVED: 'bg-sky-600/20 text-sky-300 border-sky-600/40',
  SYNTHETIC: 'bg-amber-600/20 text-amber-300 border-amber-600/40',
  'MODEL OUTPUT': 'bg-violet-600/20 text-violet-300 border-violet-600/40',
  REVIEWED: 'bg-teal-600/20 text-teal-300 border-teal-600/40',
  UNVERIFIED: 'bg-red-600/20 text-red-300 border-red-600/40',
  'EVIDENCE INCOMPLETE': 'bg-orange-600/20 text-orange-300 border-orange-600/40',
  'No data': 'bg-neutral-700/30 text-neutral-300 border-neutral-600',
  MIXED: 'bg-yellow-600/20 text-yellow-300 border-yellow-600/40',
};

export function Badge({ label }: { label: string }) {
  const c = STATUS_COLORS[label] ?? 'bg-neutral-700/30 text-neutral-300 border-neutral-600';
  return <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${c}`}>{label}</span>;
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="card text-center py-8">
      <div className="text-neutral-300 font-medium">{title}</div>
      {hint && <div className="text-neutral-500 text-sm mt-1">{hint}</div>}
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return <div className="card text-neutral-400 text-sm">Loading {what}…</div>;
}

export function Err({ message }: { message: string }) {
  return <div className="card border-red-800 text-red-300 text-sm">Error: {message}</div>;
}

export function Page({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <div className="p-4 max-w-6xl mx-auto">
      <h1 className="text-xl font-semibold">{title}</h1>
      {sub && <p className="text-neutral-400 text-sm mt-0.5 mb-3">{sub}</p>}
      <div className="mt-3 space-y-3">{children}</div>
    </div>
  );
}

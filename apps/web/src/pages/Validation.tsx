import { useQuery } from '@tanstack/react-query';
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts';
import { api } from '../api';
import { Empty, Loading, Err, Page, Badge } from '../components';
import { useUI } from '../store';

export default function Validation() {
  const { runId } = useUI();
  const q = useQuery({
    queryKey: ['validation', runId],
    queryFn: () => api.get<any>(`/runs/${runId}/validation`),
    enabled: !!runId,
  });
  if (!runId) return <Page title="Validation"><Empty title="No run selected" hint="Pick a run on the Map screen." /></Page>;

  return (
    <Page title="Validation" sub="Held-out occurrences rank in top areas? Unlabelled ground is never treated as barren. Spatial splits only.">
      {q.isLoading && <Loading what="validation" />}
      {q.isError && <Err message={(q.error as Error).message} />}
      {q.data && (
        <>
          <div className="grid md:grid-cols-4 gap-3">
            <Stat label="AUC (train)" value={fmt(q.data.auc_train)} />
            <Stat label="Random baseline" value="0.500" />
            <Stat label="Held-out hit rate (top 10%)" value={q.data.heldout?.ok ? `${((q.data.heldout.hit_rate ?? 0) * 100).toFixed(0)}% (${q.data.heldout.n_hits}/${q.data.heldout.n_heldout})` : '—'} />
            <Stat label="Labels" value={q.data.label_sufficiency?.n_training_occurrences != null ? `${q.data.label_sufficiency.n_training_occurrences} train` : '—'} />
          </div>
          {!q.data.label_sufficiency?.wofe_ml_enabled && (
            <div className="card text-amber-300 text-sm">{q.data.label_sufficiency?.message} <Badge label="MODEL OUTPUT" /></div>
          )}
          <CurveCard title="Success-rate curve (% occurrences captured vs % area)" curve={q.data.success_rate} />
          <CurveCard title="Prediction-rate curve (HELD-OUT occurrences — headline validation)" curve={q.data.prediction_rate} />
          {q.data.heldout_names?.length > 0 && (
            <div className="card font-mono text-xs">Held out: {q.data.heldout_names.join(', ')}</div>
          )}
        </>
      )}
    </Page>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="card"><div className="label">{label}</div><div className="font-mono text-lg">{value}</div></div>;
}
function fmt(v: number | null | undefined) { return v == null ? '—' : v.toFixed(3); }

function CurveCard({ title, curve }: { title: string; curve: any }) {
  if (!curve?.ok) return <div className="card"><div className="font-medium">{title}</div><p className="text-neutral-500 text-sm">{curve?.reason ?? 'Not computed.'}</p></div>;
  const data = curve.xs.map((x: number, i: number) => ({ area: +(x * 100).toFixed(1), captured: +((curve.ys[i] as number) * 100).toFixed(1), random: +(x * 100).toFixed(1) }));
  return (
    <div className="card">
      <div className="font-medium">{title} <span className="font-mono text-xs text-neutral-400">AUC {curve.auc?.toFixed(3)}</span></div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data}>
          <XAxis dataKey="area" label={{ value: '% area', position: 'insideBottomRight' }} />
          <YAxis label={{ value: '% captured', angle: -90 }} />
          <Tooltip />
          <Legend />
          <ReferenceLine y={100} stroke="#525252" strokeDasharray="3 3" />
          <Line type="monotone" dataKey="captured" name="model" stroke="#d9a441" dot={false} />
          <Line type="monotone" dataKey="random" name="random" stroke="#525252" dot={false} strokeDasharray="5 5" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

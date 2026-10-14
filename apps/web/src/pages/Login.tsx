import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { DEMO_MODE } from '../constants';
import { useUI } from '../store';

function friendly(msg: string): string {
  if (/failed to fetch|networkerror|load failed/i.test(msg || '')) {
    return 'Waking the server — up to a minute on the free tier. Please wait and retry.';
  }
  return msg;
}

export default function Login() {
  const nav = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [waking, setWaking] = useState(false);
  const [demoAvailable, setDemoAvailable] = useState(DEMO_MODE);

  useEffect(() => {
    // Ask the API whether one-click demo login is enabled (no secret in bundle).
    // On Render free tier the first request can take up to a minute (cold start).
    let cancelled = false;
    const t = setTimeout(() => { if (!cancelled) setWaking(true); }, 4000);
    api.get<{ demo_mode: boolean }>('/auth/demo-config')
      .then((j) => { if (!cancelled && j.demo_mode) setDemoAvailable(true); })
      .catch(() => { /* offline / waking — button stays hidden until reachable */ })
      .finally(() => { if (!cancelled) { clearTimeout(t); setWaking(false); } });
    return () => { cancelled = true; clearTimeout(t); };
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const r = await api.post<{ access_token: string }>('/auth/login', { email, password });
      localStorage.setItem('mwamba_token', r.access_token);
      // land on the last active project's map, else workspace
      const pid = useUI.getState().projectId;
      nav(pid ? '/map' : '/');
    } catch (ex: any) { setErr(friendly(ex.message)); } finally { setBusy(false); }
  }

  async function tryDemo() {
    setDemoBusy(true); setErr('');
    const t = setTimeout(() => setWaking(true), 4000);
    try {
      const r = await api.post<{ access_token: string }>('/auth/demo', {});
      clearTimeout(t); setWaking(false);
      localStorage.setItem('mwamba_token', r.access_token);
      const pid = useUI.getState().projectId;
      nav(pid ? '/map' : '/');
    } catch (ex: any) { clearTimeout(t); setWaking(false); setErr(friendly(ex.message)); } finally { setDemoBusy(false); }
  }

  return (
    <div className="min-h-screen grid md:grid-cols-2">
      {/* branded side panel */}
      <div className="hidden md:flex flex-col justify-between p-10 bg-gradient-to-br from-neutral-900 via-neutral-950 to-black border-r border-neutral-800">
        <div>
          <div className="font-bold text-3xl text-amber-400">MWAMBA</div>
          <div className="text-neutral-400 mt-1">Malawi Mineral Exploration Intelligence Platform</div>
        </div>
        <div className="space-y-3 text-neutral-300">
          <p className="text-lg">Where should we look next for commodity X — why there, how confident are we, and what is missing?</p>
          <ul className="text-sm list-disc ml-5 text-neutral-400">
            <li>Ranked, explainable, field-ready exploration targets</li>
            <li>Every record labelled: sourced · derived · synthetic · model output · reviewed</li>
            <li>Scores are relative rankings — never deposit probabilities</li>
          </ul>
        </div>
        <div className="text-xs text-neutral-600">Built for GSD · juniors · researchers · organised small-scale miners</div>
      </div>
      {/* form */}
      <div className="p-6 flex items-start md:items-center justify-center">
        <form onSubmit={submit} className="card w-full max-w-sm space-y-3">
          <h1 className="text-xl font-semibold">Sign in</h1>
          {waking && <div className="text-amber-300 text-sm">Waking the server — up to a minute on the free tier…</div>}
          <div><div className="label">Email</div><input className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div><div className="label">Password</div><input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
          {err && <div className="text-red-300 text-sm">{err}</div>}
          <button className="btn w-full" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
          {demoAvailable && (
            <button type="button" className="btn-ghost w-full border border-amber-500/40 text-amber-300" disabled={demoBusy} onClick={tryDemo}>
              {demoBusy ? 'Opening demo…' : 'Try the demo (no password needed)'}
            </button>
          )}
          <p className="text-neutral-500 text-xs">Live demo — uploads and new runs reset when the server restarts.</p>
        </form>
      </div>
    </div>
  );
}

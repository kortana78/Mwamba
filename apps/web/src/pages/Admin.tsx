import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { Loading, Err, Page } from '../components';

export default function Admin() {
  const users = useQuery({ queryKey: ['users'], queryFn: () => api.get<any>('/admin/users') });
  const auditQ = useQuery({ queryKey: ['audit'], queryFn: () => api.get<any>('/admin/audit?limit=100') });
  const ext = useQuery({ queryKey: ['ext'], queryFn: () => api.get<any>('/extractions?review_state=pending') });
  const src = useQuery({ queryKey: ['sources'], queryFn: () => api.get<any>('/sources/registry') });
  const [verify, setVerify] = useState<any>(null);
  const [key, setKey] = useState('');

  async function reviewExt(id: string, state: string) {
    await api.patch(`/extractions/${id}`, { review_state: state });
    ext.refetch();
  }

  return (
    <Page title="Admin" sub="Users, audit log, API keys, review queue, source registry.">
      <div className="card">
        <div className="font-medium mb-1">Review queue — report extractions ({ext.data?.items.length ?? '…'})</div>
        <p className="text-xs text-neutral-400 mb-2">Nothing here enters analysis until a geologist accepts it.</p>
        {(ext.data?.items ?? []).map((e: any) => (
          <div key={e.id} className="font-mono text-xs border-b border-neutral-800 py-1 flex gap-2 items-center flex-wrap">
            <span>{e.kind}</span><span>p.{e.page}</span>
            <span className="text-neutral-400">{e.snippet.slice(0, 120)}…</span>
            <button className="btn-ghost" onClick={() => reviewExt(e.id, 'accepted')}>Accept</button>
            <button className="btn-ghost" onClick={() => reviewExt(e.id, 'rejected')}>Reject</button>
          </div>
        ))}
        {ext.data?.items.length === 0 && <p className="text-sm text-neutral-500">Queue empty.</p>}
      </div>

      <div className="grid md:grid-cols-2 gap-3">
        <div className="card">
          <div className="font-medium mb-1">Users</div>
          {users.isLoading ? <Loading what="users" /> : users.isError ? <Err message={(users.error as Error).message} /> :
            (users.data?.items ?? []).map((u: any) => <div key={u.id} className="font-mono text-xs">{u.email} · {u.role}</div>)}
          <div className="font-medium mt-3 mb-1">API keys</div>
          <button className="btn-ghost" onClick={async () => setKey((await api.post<any>('/admin/api-keys')).api_key)}>Create key</button>
          {key && <div className="font-mono text-xs mt-1 break-all">Store once: {key}</div>}
        </div>
        <div className="card">
          <div className="font-medium mb-1">Audit log (latest 100)</div>
          {(auditQ.data?.items ?? []).slice(0, 20).map((a: any) => (
            <div key={a.id} className="font-mono text-xs border-b border-neutral-800/60 py-0.5">{a.at} · {a.action} · {a.entity}/{a.entity_id}</div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="font-medium mb-1">Source registry</div>
        <button className="btn-ghost mb-2" onClick={async () => setVerify(await api.post('/sources/registry/verify'))}>Verify reachability now</button>
        {verify && <pre className="font-mono text-xs bg-black/40 rounded p-2 overflow-x-auto">{JSON.stringify(verify, null, 1)}</pre>}
        {(src.data?.sources ?? []).map((s: any) => (
          <div key={s.id} className="text-xs py-1 border-b border-neutral-800/60">
            <span className="font-medium">{s.name}</span> <span className="text-neutral-500">[{s.access}]</span>
            <div className="text-neutral-400">{s.pipeline}</div>
          </div>
        ))}
      </div>
    </Page>
  );
}

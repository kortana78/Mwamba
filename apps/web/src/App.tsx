import { NavLink, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { api, token } from './api';
import Login from './pages/Login';
import Home from './pages/Home';
import MapPage from './pages/MapPage';
import Targets from './pages/Targets';
import TargetDossier from './pages/TargetDossier';
import DataLibrary from './pages/DataLibrary';
import Ingest from './pages/Ingest';
import Models from './pages/Models';
import Validation from './pages/Validation';
import Reports from './pages/Reports';
import Admin from './pages/Admin';

const LINKS = [
  ['/', 'Workspace'], ['/map', 'Map'], ['/targets', 'Targets'], ['/data', 'Data'],
  ['/ingest', 'Ingest'], ['/models', 'Models'], ['/validation', 'Validation'],
  ['/reports', 'Reports'], ['/admin', 'Admin'],
];

function Shell() {
  const nav = useNavigate();
  const [demoMode, setDemoMode] = useState(false);
  useEffect(() => {
    api.get<{ demo_mode: boolean }>('/auth/demo-config')
      .then((j) => setDemoMode(!!j.demo_mode))
      .catch(() => {});
  }, []);
  return (
    <div className="min-h-screen">
      {demoMode && (
        <div className="bg-amber-500/15 border-b border-amber-500/30 text-amber-200 text-xs px-4 py-1.5 text-center">
          Live demo — uploads and new runs reset when the server restarts. Scores are relative rankings, never deposit probabilities.
        </div>
      )}
      <header className="h-14 flex items-center gap-3 px-4 border-b border-neutral-800 sticky top-0 bg-neutral-950/95 z-10">
        <span className="font-bold text-amber-400">MWAMBA</span>
        <span className="text-xs text-neutral-500 hidden md:inline">Malawi Mineral Exploration Intelligence</span>
        <nav className="flex gap-1 ml-4 flex-wrap">
          {LINKS.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/'}
              className={({ isActive }) => `px-2 py-1 rounded text-sm ${isActive ? 'bg-neutral-800 text-amber-300' : 'text-neutral-300 hover:bg-neutral-900'}`}>
              {label}
            </NavLink>
          ))}
        </nav>
        <button className="btn-ghost ml-auto text-xs" onClick={() => { localStorage.removeItem('mwamba_token'); nav('/login'); }}>
          Sign out
        </button>
      </header>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/map" element={<MapPage />} />
        <Route path="/targets" element={<Targets />} />
        <Route path="/targets/:id" element={<TargetDossier />} />
        <Route path="/data" element={<DataLibrary />} />
        <Route path="/ingest" element={<Ingest />} />
        <Route path="/models" element={<Models />} />
        <Route path="/validation" element={<Validation />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </div>
  );
}

export default function App() {
  if (!token() && window.location.pathname !== '/login') {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" />} />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={<Shell />} />
    </Routes>
  );
}

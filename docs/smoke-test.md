# Manual smoke test (5 minutes, local or live)

Use when Playwright cannot run (no browser / CI minutes). Every value is read
from the app's own API — no invented numbers.

## Setup

```powershell
pip install -r requirements.txt
uvicorn apps.api.app.main:app --port 8000
# new terminal:
Set-Location apps/web; npm install; npm run dev
# App: http://localhost:5173   API health: http://localhost:8000/health
```

## Path

1. **Login**: open `/login` → "Try the demo" (demo mode) or
   `admin@mwamba.local / Mwamba123!` locally. Expect redirect to Workspace.
2. **Projects**: two seeded projects visible —
   "Chitipa Gold — Synthetic demo (SYNTHETIC)" badge `SYNTHETIC`,
   "Chitipa Gold — Real data (evidence incomplete)" badge `No data`/`VERIFIED`/
   `EVIDENCE INCOMPLETE` depending on runs.
3. **Map**: open the synthetic project map. Toggle structures/geology/geochem.
   Click a feature → inspector shows attributes + status badge.
4. **Run**: Models → method `weighted` → defaults
   (top 5% · 200 000 m² · 500 m merge · max 20) → Run analysis.
   Expect `Run queued: <id>`, progress → `done` within ~1 min (grid 200 m).
5. **Gate (synthetic)**: run row shows `sufficient`; metrics
   `evidence_gate.present_groups` covers structure + host_lithology +
   alteration_or_geochem; `grid_meta.n_targets` is 1–20.
6. **Targets**: Targets page auto-selects latest done run → ranked table
   (mean/max/coverage/area). Open dossier #1 → score breakdown, missing
   evidence, constraints, next steps. Download dossier PDF → starts with `%PDF`.
7. **Validation**: Validation page → success + prediction-rate curves render,
   AUC shown, held-out names listed (synthetic fixtures have ≥3 occurrences).
8. **Exports**: Reports → Targets GeoJSON/CSV/KML download (200 each).
9. **Gate (real data)**: switch to the real-data project → Models → Run.
   Expect `insufficient evidence`, `n_targets: 0`, banner
   "INSUFFICIENT EVIDENCE — not a targeting result", project badge
   `EVIDENCE INCOMPLETE`. Targets page is empty (honest, not an error).
10. **Determinism**: rerun the synthetic run (`POST /runs/{id}/rerun`) →
    identical grid bytes (covered by `test_full_run_weighted_and_dossier`).

## Automated equivalent

```powershell
pytest apps/api/tests packages/geo/tests -q   # 35 tests
Set-Location apps/web; npm test               # vitest (e2e excluded)
npx playwright test                           # needs browsers + both servers
```

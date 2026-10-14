"""D: run weighted + fuzzy on the REAL-data Chitipa project and print honest numbers.

Usage (API must be running):
    python scripts/run_real_demo.py [--base http://127.0.0.1:8000]

Not executed in CI here per operator instruction; run it on a live server.
Prints: score stats, coverage, AUC, held-out result, target count — whatever they are.
"""
import json
import sys
import time
import urllib.request

BASE = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "http://127.0.0.1:8000"
EMAIL, PASSWORD = "admin@mwamba.local", "Mwamba123!"


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


tok = call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})["access_token"]
projs = call("GET", "/projects", token=tok)["items"]
real = next((p for p in projs if "real data" in p["name"]), None)
if real is None:
    sys.exit("No 'real data' project seeded. Check data/real/ + restart API.")
pid = real["id"]
print("project:", real["name"], "| status:", real["status_label"],
      "| commodity:", real["commodity"], "| datasets:", real["n_datasets"])
proj = call("GET", f"/projects/{pid}", token=tok)
for d in proj["datasets"]:
    print(f"  - {d['kind']:12s} {d['name'][:60]:62s} [{d['status_label']}] n={d['feature_count']}")

for method in ("weighted", "fuzzy"):
    weights = {"dist_structure": 0.3, "fault_density": 0.15, "lithology": 0.2,
               "geochem_au": 0.15, "dem_slope": 0.2}
    run = call("POST", f"/runs?project_id={pid}", token=tok, body={
        "method": method,
        "config": {"grid_m": 200, "weights": weights, "target_percentile": 90.0,
                   "target_min_area_m2": 40000.0},
        "seed": 42, "holdout_fraction": 0.3})
    rid = run["id"]
    for _ in range(60):
        time.sleep(5)
        r = call("GET", f"/runs/{rid}", token=tok)
        if r["status"] in ("done", "failed"):
            break
    print(f"\n== {method}: {r['status']} ==")
    if r["status"] == "failed":
        print("error:", r["error"][:600])
        continue
    m = r["metrics"]
    print("layers used:", sorted((m.get("recipes") or {}).keys()))
    gate = m.get("evidence_gate") or {}
    print("evidence gate: sufficient =", gate.get("sufficient"),
          "| present:", sorted((gate.get("present_groups") or {}).keys()),
          "| missing:", gate.get("missing_groups"))
    print("score mean/max: %.4f / %.4f | coverage: %.2f | targets: %d"
          % (m["score_stats"]["mean"], m["score_stats"]["max"],
             m["coverage_mean"], r["grid_meta"]["n_targets"]))
    print("auc_train:", m.get("auc_train"), "| heldout:", json.dumps(m.get("heldout")))
    print("occurrences:", len(m.get("train_names", [])), "train /",
          len(m.get("heldout_names", [])), "held out | skipped (other commodity):",
          m.get("n_skipped_other_commodity"))
    v = call("GET", f"/runs/{rid}/validation", token=tok)
    print("label gate:", (v.get("label_sufficiency") or {}).get("message"))

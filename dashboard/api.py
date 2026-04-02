"""
CodeAudit Dashboard API
Serves real audit data from the local filesystem.
Run: uvicorn api:app --reload --port 8787
Then open: http://localhost:8787
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="CodeAudit Dashboard", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers ───────────────────────────────────────────────────

def find_memory_dir(start: Path | None = None) -> Path | None:
    """Walk up from start looking for .code-audit/memory/"""
    base = start or Path.cwd()
    for parent in [base, *base.parents]:
        candidate = parent / ".code-audit" / "memory"
        if candidate.exists():
            return candidate
    return None

def find_reports_dir(start: Path | None = None) -> Path | None:
    """Walk up from start looking for .audit/reports/"""
    base = start or Path.cwd()
    for parent in [base, *base.parents]:
        candidate = parent / ".audit" / "reports"
        if candidate.exists():
            return candidate
    return None

def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None

# ── API Routes ────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "3.0.0"}


@app.get("/api/history")
def get_history():
    """Return audit_history.json from team memory."""
    mem = find_memory_dir()
    if not mem:
        return JSONResponse({"error": "No memory dir found", "records": []})
    path = mem / "audit_history.json"
    data = load_json(path) if path.exists() else []
    return {"records": data or [], "source": str(path)}


@app.get("/api/reports")
def list_reports():
    """List all audit report JSON files."""
    reports_dir = find_reports_dir()
    if not reports_dir:
        return {"reports": [], "error": "No .audit/reports/ directory found"}
    files = sorted(reports_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
    return {"reports": [f.name for f in files[:50]], "dir": str(reports_dir)}


@app.get("/api/reports/latest")
def latest_report():
    """Return the most recent full audit report."""
    reports_dir = find_reports_dir()
    if not reports_dir:
        return JSONResponse({"error": "No reports directory found"}, status_code=404)
    files = sorted(reports_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
    if not files:
        return JSONResponse({"error": "No reports found"}, status_code=404)
    data = load_json(files[0])
    return data or JSONResponse({"error": "Could not parse report"}, status_code=500)


@app.get("/api/reports/{report_id}")
def get_report(report_id: str):
    reports_dir = find_reports_dir()
    if not reports_dir:
        return JSONResponse({"error": "No reports directory"}, status_code=404)
    path = reports_dir / f"{report_id}.json"
    if not path.exists():
        path = reports_dir / report_id
    if not path.exists():
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return load_json(path)


@app.get("/api/memory/decisions")
def get_decisions():
    mem = find_memory_dir()
    if not mem:
        return {"decisions": []}
    path = mem / "decisions.json"
    return {"decisions": load_json(path) or []}


@app.get("/api/memory/patterns")
def get_patterns():
    mem = find_memory_dir()
    if not mem:
        return {"patterns": []}
    path = mem / "patterns.json"
    return {"patterns": load_json(path) or []}


@app.get("/api/summary")
def get_summary():
    """Aggregate summary from audit history for dashboard stats."""
    mem = find_memory_dir()
    history = []
    if mem:
        path = mem / "audit_history.json"
        if path.exists():
            history = load_json(path) or []

    if not history:
        return {"total_reviews": 0, "all_time_cost": 0.0, "records": []}

    total_cost = sum(r.get("cost_usd", 0.0) for r in history)
    total_findings = sum(r.get("finding_counts", {}).get("total", 0) for r in history)
    return {
        "total_reviews": len(history),
        "all_time_cost": total_cost,
        "total_findings": total_findings,
        "records": history[-10:],  # last 10
    }


# ── Serve dashboard SPA ───────────────────────────────────────
DASHBOARD_DIR = Path(__file__).parent

@app.get("/")
def serve_dashboard():
    return FileResponse(DASHBOARD_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8787, reload=True)

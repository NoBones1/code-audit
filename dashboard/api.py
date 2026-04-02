"""
CodeAudit Dashboard API
Serves real audit data from the local filesystem.
Run: uvicorn api:app --reload --port 8787
Then open: http://localhost:8787
"""
from __future__ import annotations
import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

# ── Scan State ────────────────────────────────────────────────

class ScanRequest(BaseModel):
    path: str
    mode: str = "deep"

class ScanState:
    def __init__(self, scan_id: str, path: str, mode: str):
        self.scan_id = scan_id
        self.path = path
        self.mode = mode
        self.status: str = "running"  # running | done | error
        self.exit_code: int | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.stdout_lines: list[str] = []
        self.stderr_lines: list[str] = []
        self.event_queue: asyncio.Queue = asyncio.Queue()

# In-memory scan registry
_scans: dict[str, ScanState] = {}


async def _run_scan(state: ScanState) -> None:
    """Spawn code-audit subprocess and feed lines into the event queue."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "code-audit", "review",
            "--path", state.path,
            "--mode", state.mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        state.process = proc

        async def read_stream(stream, stream_type: str):
            async for raw in stream:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if stream_type == "stdout":
                    state.stdout_lines.append(line)
                    await state.event_queue.put(("log", line))
                else:
                    state.stderr_lines.append(line)
                    await state.event_queue.put(("error", line))

        await asyncio.gather(
            read_stream(proc.stdout, "stdout"),
            read_stream(proc.stderr, "stderr"),
        )

        exit_code = await proc.wait()
        state.exit_code = exit_code
        state.status = "done" if exit_code == 0 else "error"
        await state.event_queue.put(("done", str(exit_code)))

    except FileNotFoundError:
        state.status = "error"
        state.exit_code = -1
        msg = "code-audit command not found. Is it installed and on PATH?"
        state.stderr_lines.append(msg)
        await state.event_queue.put(("error", msg))
        await state.event_queue.put(("done", "-1"))
    except Exception as exc:
        state.status = "error"
        state.exit_code = -1
        msg = f"Scan failed: {exc}"
        state.stderr_lines.append(msg)
        await state.event_queue.put(("error", msg))
        await state.event_queue.put(("done", "-1"))


# ── API Routes ────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "3.0.0"}


@app.post("/api/scan")
async def start_scan(req: ScanRequest):
    """Start a new code-audit scan. Returns scan_id immediately."""
    target = Path(req.path).expanduser().resolve()
    if not target.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {req.path}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {req.path}")
    if req.mode not in ("deep", "quick", "security"):
        raise HTTPException(status_code=400, detail=f"Invalid mode: {req.mode}. Must be deep, quick, or security.")

    scan_id = uuid.uuid4().hex[:12]
    state = ScanState(scan_id=scan_id, path=str(target), mode=req.mode)
    _scans[scan_id] = state

    # Fire and forget the subprocess
    asyncio.create_task(_run_scan(state))

    return {
        "scan_id": scan_id,
        "path": str(target),
        "mode": req.mode,
        "status": "running",
    }


@app.get("/api/scan/{scan_id}/stream")
async def stream_scan(scan_id: str, request: Request):
    """SSE endpoint that streams subprocess output line by line."""
    if scan_id not in _scans:
        raise HTTPException(status_code=404, detail="Scan not found")

    state = _scans[scan_id]

    async def event_generator():
        # First, replay any lines already captured
        for line in state.stdout_lines:
            yield f"event: log\ndata: {json.dumps({'line': line})}\n\n"
        for line in state.stderr_lines:
            yield f"event: error\ndata: {json.dumps({'line': line})}\n\n"

        if state.status != "running":
            yield f"event: done\ndata: {json.dumps({'exit_code': state.exit_code})}\n\n"
            return

        # Then stream new events from the queue
        while True:
            if await request.is_disconnected():
                break
            try:
                event_type, data = await asyncio.wait_for(
                    state.event_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                # Send keepalive comment
                yield ": keepalive\n\n"
                continue

            if event_type == "done":
                yield f"event: done\ndata: {json.dumps({'exit_code': int(data)})}\n\n"
                break
            else:
                yield f"event: {event_type}\ndata: {json.dumps({'line': data})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/scan/{scan_id}/status")
def scan_status(scan_id: str):
    """Return current status of a scan."""
    if scan_id not in _scans:
        raise HTTPException(status_code=404, detail="Scan not found")
    state = _scans[scan_id]
    return {
        "scan_id": scan_id,
        "path": state.path,
        "mode": state.mode,
        "status": state.status,
        "exit_code": state.exit_code,
        "stdout_lines": len(state.stdout_lines),
        "stderr_lines": len(state.stderr_lines),
    }


@app.get("/api/folders/recent")
def recent_folders():
    """Return the last 10 unique target_paths from audit_history.json."""
    mem = find_memory_dir()
    if not mem:
        return {"folders": []}
    path = mem / "audit_history.json"
    if not path.exists():
        return {"folders": []}
    history = load_json(path) or []

    seen = set()
    folders = []
    for record in reversed(history):
        target = record.get("target_path", "")
        if target and target not in seen:
            seen.add(target)
            folders.append(target)
            if len(folders) >= 10:
                break

    return {"folders": folders}


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

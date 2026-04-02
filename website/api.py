"""
FastAPI backend for the Code Audit marketing website's "Try It" feature.

Handles file uploads, runs code-audit scans via subprocess, streams results
over SSE, and serves static pages.

Dependencies: fastapi, uvicorn, python-multipart
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

logger = logging.getLogger("code-audit-api")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_UPLOAD_BYTES = 400 * 1024 * 1024  # 400 MB
MAX_FILES_PER_UPLOAD = 1000
SCAN_TIMEOUT_SECONDS = 600  # 10 minutes
STALE_SCAN_AGE_SECONDS = 15 * 60  # 15 minutes
CLEANUP_INTERVAL_SECONDS = 5 * 60  # 5 minutes

WEBSITE_DIR = Path(__file__).resolve().parent

PAID_API_PRICING = {
    "claude-sonnet-4-6": {"input_per_1m": 3.0, "output_per_1m": 15.0, "label": "Claude Sonnet 4.6"},
    "claude-opus-4-6": {"input_per_1m": 15.0, "output_per_1m": 75.0, "label": "Claude Opus 4.6"},
    "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.0, "label": "GPT-4o"},
    "gemini-2.5-pro": {"input_per_1m": 1.25, "output_per_1m": 10.0, "label": "Gemini 2.5 Pro"},
    "coderabbit": {"monthly": 24.0, "label": "CodeRabbit (monthly/dev)"},
}

# ---------------------------------------------------------------------------
# Scan state
# ---------------------------------------------------------------------------

@dataclass
class ScanState:
    scan_id: str
    path: str
    mode: str
    status: str = "uploading"  # uploading -> running -> completed -> cleaned / failed -> cleaned
    exit_code: int | None = None
    process: asyncio.subprocess.Process | None = None
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    report_data: dict | None = None  # parsed report.json
    created_at: float = field(default_factory=time.time)


# In-memory store of all scans (keyed by scan_id)
scans: dict[str, ScanState] = {}

# ---------------------------------------------------------------------------
# Filename sanitisation
# ---------------------------------------------------------------------------

def _sanitize_path(raw: str) -> str | None:
    """Return a safe relative path string, or None if the path is invalid."""
    # Strip leading slashes and null bytes
    cleaned = raw.replace("\x00", "").lstrip("/")
    parts = Path(cleaned).parts
    # Reject any component that is ".." or starts with "."
    safe_parts: list[str] = []
    for part in parts:
        if part in ("..", "."):
            continue
        # Extra guard: strip leading dots from individual components
        stripped = part.lstrip(".")
        if not stripped:
            continue
        safe_parts.append(part)
    if not safe_parts:
        return None
    return str(Path(*safe_parts))

# ---------------------------------------------------------------------------
# Background scan runner
# ---------------------------------------------------------------------------

async def _run_scan(state: ScanState) -> None:
    """Execute code-audit review as a subprocess and stream output to the event queue."""
    try:
        state.status = "running"
        await state.event_queue.put({"event": "log", "data": f"Starting scan in {state.mode} mode..."})

        proc = await asyncio.create_subprocess_exec(
            "code-audit", "review", "--path", state.path, "--mode", state.mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        state.process = proc

        async def _read_stream(stream: asyncio.StreamReader, event_type: str, line_store: list[str]):
            async for raw_line in stream:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                line_store.append(line)
                await state.event_queue.put({"event": event_type, "data": line})

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _read_stream(proc.stdout, "log", state.stdout_lines),
                    _read_stream(proc.stderr, "error", state.stderr_lines),
                    proc.wait(),
                ),
                timeout=SCAN_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Scan %s timed out after %ds, killing process", state.scan_id, SCAN_TIMEOUT_SECONDS)
            proc.kill()
            await proc.wait()
            state.status = "failed"
            state.exit_code = -1
            await state.event_queue.put({"event": "error", "data": f"Scan timed out after {SCAN_TIMEOUT_SECONDS}s"})
            await state.event_queue.put({"event": "done", "data": "timeout"})
            return

        state.exit_code = proc.returncode

        # Try to load the report
        report_path = Path(state.path) / ".audit" / "report.json"
        if report_path.exists():
            try:
                state.report_data = json.loads(report_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read report for scan %s: %s", state.scan_id, exc)

        if proc.returncode == 0:
            state.status = "completed"
            await state.event_queue.put({"event": "done", "data": "success"})
        else:
            state.status = "failed"
            await state.event_queue.put({"event": "done", "data": f"exit_code={proc.returncode}"})

    except Exception as exc:
        logger.exception("Unexpected error running scan %s", state.scan_id)
        state.status = "failed"
        await state.event_queue.put({"event": "error", "data": str(exc)})
        await state.event_queue.put({"event": "done", "data": "crash"})

    finally:
        # Guaranteed cleanup of temp directory
        shutil.rmtree(state.path, ignore_errors=True)
        if state.status not in ("cleaned",):
            prev = state.status
            state.status = "cleaned"
            logger.info("Scan %s: %s -> cleaned (temp dir removed)", state.scan_id, prev)

# ---------------------------------------------------------------------------
# Stale scan cleanup background task
# ---------------------------------------------------------------------------

async def _stale_scan_cleanup_loop() -> None:
    """Periodically remove temp dirs for scans older than STALE_SCAN_AGE_SECONDS."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        now = time.time()
        stale_ids: list[str] = []
        for scan_id, state in list(scans.items()):
            age = now - state.created_at
            if age > STALE_SCAN_AGE_SECONDS:
                # Kill process if still running
                if state.process and state.process.returncode is None:
                    try:
                        state.process.kill()
                    except ProcessLookupError:
                        pass
                # Remove temp dir if it still exists
                if os.path.isdir(state.path):
                    shutil.rmtree(state.path, ignore_errors=True)
                    logger.info("Stale cleanup: removed temp dir for scan %s (age %.0fs)", scan_id, age)
                state.status = "cleaned"
                stale_ids.append(scan_id)
        # Optionally prune very old entries from memory (> 1 hour)
        for scan_id in list(scans.keys()):
            if now - scans[scan_id].created_at > 3600:
                del scans[scan_id]
                logger.info("Pruned in-memory state for scan %s", scan_id)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Code Audit - Try It API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8789",
        "http://127.0.0.1:8789",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def _on_startup():
    asyncio.create_task(_stale_scan_cleanup_loop())

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def upload_files(
    request: Request,
    mode: str = Form(default="quick"),
    files: list[UploadFile] = File(...),
):
    """Accept multipart file upload, preserve directory structure, start scan."""
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(status_code=400, detail=f"Too many files ({len(files)}). Maximum is {MAX_FILES_PER_UPLOAD}.")

    scan_id = uuid.uuid4().hex
    tmpdir = tempfile.mkdtemp(prefix="code_audit_")

    cumulative_size = 0
    saved_count = 0

    try:
        for upload in files:
            # Sanitize the filename (which includes the relative path from webkitdirectory)
            raw_name = upload.filename or ""
            safe_rel = _sanitize_path(raw_name)
            if safe_rel is None:
                continue  # skip unsanitizable names

            dest = Path(tmpdir) / safe_rel

            # Read content
            content = await upload.read()
            cumulative_size += len(content)
            if cumulative_size > MAX_UPLOAD_BYTES:
                # Clean up and reject
                shutil.rmtree(tmpdir, ignore_errors=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds maximum size of {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
                )

            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            saved_count += 1

        if saved_count == 0:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="No valid files received.")

    except HTTPException:
        raise
    except Exception as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        logger.exception("Upload failed for scan %s", scan_id)
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")

    # Create scan state
    state = ScanState(scan_id=scan_id, path=tmpdir, mode=mode)
    scans[scan_id] = state

    # Start the scan in the background
    asyncio.create_task(_run_scan(state))

    return JSONResponse({
        "scan_id": scan_id,
        "file_count": saved_count,
        "total_bytes": cumulative_size,
        "mode": mode,
    })


@app.post("/api/scan/github")
async def scan_github(req: Request):
    """Clone a public GitHub repo to a temp dir and start a scan."""
    body = await req.json()
    repo_url = body.get("repo_url", "").strip()
    mode = body.get("mode", "quick")

    if not repo_url or "github.com" not in repo_url:
        raise HTTPException(status_code=400, detail="Invalid GitHub URL.")

    scan_id = uuid.uuid4().hex
    tmpdir = tempfile.mkdtemp(prefix="code_audit_")

    async def _clone_and_scan(state: ScanState) -> None:
        try:
            state.status = "cloning"
            await state.event_queue.put({"event": "log", "data": f"Cloning {repo_url}..."})

            clone_proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth=1", repo_url, state.path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(clone_proc.wait(), timeout=120)
            except asyncio.TimeoutError:
                clone_proc.kill()
                raise RuntimeError("Git clone timed out after 120s")

            if clone_proc.returncode != 0:
                err = (await clone_proc.stderr.read()).decode(errors="replace")
                raise RuntimeError(f"Git clone failed: {err[:200]}")

            await state.event_queue.put({"event": "log", "data": "Clone complete. Starting review..."})
            await _run_scan(state)
        except Exception as exc:
            state.status = "failed"
            await state.event_queue.put({"event": "error", "data": str(exc)})
            await state.event_queue.put({"event": "done", "data": "clone_error"})
            shutil.rmtree(state.path, ignore_errors=True)

    state = ScanState(scan_id=scan_id, path=tmpdir, mode=mode)
    scans[scan_id] = state
    asyncio.create_task(_clone_and_scan(state))

    return JSONResponse({"scan_id": scan_id, "repo_url": repo_url, "mode": mode})


@app.get("/api/scan/{scan_id}/stream")
async def scan_stream(scan_id: str, request: Request):
    """SSE endpoint that streams scan output in real-time."""
    state = scans.get(scan_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Scan not found.")

    async def _event_generator():
        # First, replay any lines already collected
        for line in list(state.stdout_lines):
            yield f"event: log\ndata: {json.dumps({'line': line})}\n\n"
        for line in list(state.stderr_lines):
            yield f"event: error\ndata: {json.dumps({'line': line})}\n\n"

        # If scan already finished, send done and exit
        if state.status in ("completed", "failed", "cleaned"):
            yield f"event: done\ndata: {json.dumps({'status': state.status})}\n\n"
            return

        # Stream new events as they arrive
        while True:
            if await request.is_disconnected():
                return

            try:
                event = await asyncio.wait_for(state.event_queue.get(), timeout=5.0)
                evt_type = event.get("event", "log")
                evt_data = event.get("data", "")
                yield f"event: {evt_type}\ndata: {json.dumps({'line': evt_data})}\n\n"
                if evt_type == "done":
                    return
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(_event_generator(), media_type="text/event-stream")


@app.get("/api/scan/{scan_id}/result")
async def scan_result(scan_id: str):
    """Return scan result and metadata."""
    state = scans.get(scan_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Scan not found.")

    return JSONResponse({
        "scan_id": state.scan_id,
        "status": state.status,
        "mode": state.mode,
        "exit_code": state.exit_code,
        "created_at": state.created_at,
        "stdout_lines": state.stdout_lines,
        "stderr_lines": state.stderr_lines,
        "report": state.report_data,
    })


@app.get("/api/pricing")
async def pricing():
    """Return model pricing comparison data."""
    return JSONResponse(PAID_API_PRICING)


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = WEBSITE_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/try", response_class=HTMLResponse)
async def serve_try():
    try_path = WEBSITE_DIR / "try.html"
    if not try_path.exists():
        raise HTTPException(status_code=404, detail="try.html not found")
    return HTMLResponse(try_path.read_text(encoding="utf-8"))


# Catch-all for static files in the website directory
@app.get("/static/{file_path:path}")
async def serve_static(file_path: str):
    safe = _sanitize_path(file_path)
    if safe is None:
        raise HTTPException(status_code=400, detail="Invalid path")
    full_path = WEBSITE_DIR / safe
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # Ensure we're not escaping the website directory
    try:
        full_path.resolve().relative_to(WEBSITE_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")
    return FileResponse(full_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8789)

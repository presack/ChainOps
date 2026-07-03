"""FastAPI web UI for ChainOps -- personal-mode only for now (no
SERVER_MODE/TRAINING_MODE auth; StealthOps built those in after its
personal-mode core was working, same order here).

No template engine (no Jinja2, no templates/ dir) -- HTML is generated
via Python f-strings directly, matching StealthOps' web_ui.py. Tailwind
via CDN for styling (dark slate background, cyan accent) so the two
tools feel like siblings without vendoring a stylesheet.

Result rendering reuses formatter.format_cli_report()'s "=== SECTION ===
[source: ...]" / "Label: value" text convention -- same approach
report.py already uses for PDF generation -- so the report structure has
one source of truth instead of three parallel renderers (CLI, PDF, web).

Async job pattern for queries, matching StealthOps: POST /query/start
spawns a background thread running core_ops.run_all_staged(), returns a
job_id; the client polls GET /query/status/{job_id} until done, then
swaps in the server-rendered result HTML fragment.
"""

from __future__ import annotations

import re
import threading
import uuid
from html import escape
from typing import Any

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse

from core_ops import run_all_staged
from formatter import format_cli_report

_LABEL_VALUE_RE = re.compile(r"^(\s*(?:-\s+)?)([A-Za-z][^:\n]{0,45}?)(: )(.+)$")

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _section_label(line: str) -> str:
    parts = [p.strip() for p in line.split("===") if p.strip()]
    if not parts:
        return escape(line.strip())
    title = escape(parts[0])
    if len(parts) >= 2:
        source = escape(parts[1].strip("[] ").strip())
        return f"{title} <span class='text-slate-500 text-xs font-normal'>[{source}]</span>"
    return title


def render_result_html(result: dict[str, Any]) -> str:
    """Parse format_cli_report()'s section/label-value text into styled
    HTML cards."""
    text = format_cli_report(result)
    parts: list[str] = []
    in_card = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("==="):
            if in_card:
                parts.append("</div></div>")
            parts.append(
                "<div class='bg-slate-800/70 rounded-xl shadow-xl p-4 mb-3'>"
                f"<h3 class='text-cyan-400 font-semibold mb-2'>{_section_label(line)}</h3>"
                "<div class='text-sm space-y-1'>"
            )
            in_card = True
        elif not line.strip():
            continue
        else:
            is_flagged = line.strip().startswith(("Error:", "[!]"))
            css = "text-red-400 font-medium" if is_flagged else "text-slate-200"
            match = _LABEL_VALUE_RE.match(line)
            if match:
                _, label, _, value = match.groups()
                parts.append(
                    f"<div class='flex gap-2 {css}'><span class='text-slate-400'>{escape(label)}:</span>"
                    f"<span>{escape(value)}</span></div>"
                )
            else:
                parts.append(f"<div class='{css}'>{escape(line.strip())}</div>")
    if in_card:
        parts.append("</div></div>")
    return "".join(parts)


def _page_shell(body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>ChainOps</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
  <div class="max-w-3xl mx-auto px-4 py-8">
    <h1 class="text-2xl font-bold text-cyan-400 mb-1">ChainOps</h1>
    <p class="text-slate-400 text-sm mb-6">Blockchain address/tx recon &mdash; BTC, Tron, ETH</p>
    {body}
  </div>
</body>
</html>"""


_QUERY_FORM = """
<form id="query-form" class="bg-slate-800/70 rounded-xl shadow-xl p-4 mb-4 flex gap-2">
  <input id="target" name="target" type="text" placeholder="BTC/Tron/ETH address or .eth name" autocomplete="off"
         class="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-cyan-500" />
  <button type="submit" class="bg-cyan-600 hover:bg-cyan-500 rounded-lg px-4 py-2 text-sm font-medium">Query</button>
</form>
<div id="result"></div>
<script>
  const form = document.getElementById('query-form');
  const resultDiv = document.getElementById('result');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const target = document.getElementById('target').value.trim();
    if (!target) return;
    resultDiv.innerHTML = '<p class="text-slate-400 text-sm">Gathering results...</p>';
    let startData;
    try {
      const startResp = await fetch('/query/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'target=' + encodeURIComponent(target)
      });
      startData = await startResp.json();
    } catch (err) {
      resultDiv.innerHTML = '<p class="text-red-400 text-sm">request failed: ' + err + '</p>';
      return;
    }
    if (startData.error) {
      resultDiv.innerHTML = '<p class="text-red-400 text-sm">' + startData.error + '</p>';
      return;
    }
    const jobId = startData.job_id;
    const poll = setInterval(async () => {
      const statusResp = await fetch('/query/status/' + jobId);
      const statusData = await statusResp.json();
      if (statusData.error) {
        clearInterval(poll);
        resultDiv.innerHTML = '<p class="text-red-400 text-sm">' + statusData.error + '</p>';
        return;
      }
      if (statusData.done) {
        clearInterval(poll);
        resultDiv.innerHTML = statusData.html;
      }
    }, 800);
  });
</script>
"""


def build_app() -> FastAPI:
    app = FastAPI(title="ChainOps")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return _page_shell(_QUERY_FORM)

    @app.post("/query/start")
    def query_start(target: str = Form(...)) -> JSONResponse:
        target = target.strip()
        if not target:
            return JSONResponse({"error": "target is required"}, status_code=400)

        job_id = uuid.uuid4().hex
        with _jobs_lock:
            _jobs[job_id] = {"done": False, "html": "", "error": None}

        def _worker() -> None:
            try:
                result = run_all_staged(target)
                html = render_result_html(result)
            except Exception as exc:
                with _jobs_lock:
                    _jobs[job_id] = {"done": True, "html": "", "error": f"query failed: {exc}"}
                return
            with _jobs_lock:
                _jobs[job_id] = {"done": True, "html": html, "error": None}

        threading.Thread(target=_worker, daemon=True).start()
        return JSONResponse({"job_id": job_id})

    @app.get("/query/status/{job_id}")
    def query_status(job_id: str) -> JSONResponse:
        with _jobs_lock:
            job = _jobs.get(job_id)
        if job is None:
            return JSONResponse({"error": "unknown job_id"}, status_code=404)
        return JSONResponse(job)

    return app

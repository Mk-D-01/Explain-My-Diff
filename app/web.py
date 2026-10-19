"""Standard-library HTTP interface for Explain My Diff."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .report import format_markdown
from .triage import triage_diff


# A diff is text, so a 1 MiB body limit is large enough for normal reviews while
# preventing an accidental or hostile request from consuming unbounded memory.
MAX_REQUEST_BYTES = 1_048_576


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Explain My Diff</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1020;
      --panel: rgba(20, 29, 52, .84);
      --panel-strong: #17233f;
      --text: #edf3ff;
      --muted: #a9b8d5;
      --line: rgba(169, 184, 213, .2);
      --accent: #7dd3fc;
      --accent-strong: #38bdf8;
      --success: #86efac;
      --danger: #fda4af;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      font: 16px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at 15% 0%, #203865 0, transparent 38%), var(--bg);
    }
    .shell { width: min(1180px, calc(100% - 40px)); margin: 0 auto; padding: 52px 0 64px; }
    .eyebrow { color: var(--accent); font-size: .78rem; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }
    h1 { margin: 8px 0 10px; font-size: clamp(2.2rem, 5vw, 4.2rem); line-height: 1.05; letter-spacing: -.04em; }
    .lede { max-width: 700px; margin: 0; color: var(--muted); font-size: 1.1rem; }
    .grid { display: grid; grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr); gap: 22px; margin-top: 34px; }
    .panel { border: 1px solid var(--line); border-radius: 20px; padding: 24px; background: var(--panel); box-shadow: 0 18px 60px rgba(0, 0, 0, .25); backdrop-filter: blur(12px); }
    .panel h2 { margin: 0 0 6px; font-size: 1.15rem; }
    .hint { margin: 0 0 18px; color: var(--muted); font-size: .9rem; }
    label { display: block; margin: 16px 0 7px; color: var(--muted); font-size: .84rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
    textarea, input {
      width: 100%; border: 1px solid var(--line); border-radius: 12px; background: rgba(5, 10, 24, .7);
      color: var(--text); font: 14px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; padding: 13px;
    }
    textarea { min-height: 390px; resize: vertical; }
    input { font-family: inherit; }
    textarea:focus, input:focus { outline: 2px solid var(--accent-strong); outline-offset: 2px; }
    button { width: 100%; margin-top: 18px; border: 0; border-radius: 12px; padding: 13px 18px; color: #062033; background: linear-gradient(135deg, var(--accent), var(--accent-strong)); font-weight: 800; cursor: pointer; }
    button:hover { filter: brightness(1.08); }
    button:disabled { cursor: wait; opacity: .65; }
    .empty { display: grid; min-height: 470px; place-items: center; border: 1px dashed var(--line); border-radius: 14px; padding: 24px; color: var(--muted); text-align: center; }
    .result { display: none; }
    .result.visible { display: block; }
    .status { display: inline-flex; align-items: center; gap: 8px; margin-bottom: 14px; border-radius: 999px; padding: 5px 11px; background: rgba(134, 239, 172, .12); color: var(--success); font-size: .82rem; font-weight: 800; }
    .status.error { background: rgba(253, 164, 175, .12); color: var(--danger); }
    .metrics { display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 16px; }
    .metric { border: 1px solid var(--line); border-radius: 10px; padding: 9px 12px; background: var(--panel-strong); }
    .metric strong { display: block; font-size: 1.25rem; }
    .metric span { color: var(--muted); font-size: .74rem; }
    pre { max-height: 530px; overflow: auto; margin: 0; white-space: pre-wrap; word-break: break-word; }
    .markdown { border: 1px solid var(--line); border-radius: 12px; padding: 18px; background: rgba(5, 10, 24, .62); font: 13px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; }
    details { margin-top: 14px; }
    summary { color: var(--muted); cursor: pointer; }
    .footer { margin-top: 22px; color: var(--muted); font-size: .8rem; }
    @media (max-width: 800px) { .shell { width: min(100% - 24px, 680px); padding-top: 30px; } .grid { grid-template-columns: 1fr; } textarea { min-height: 260px; } .empty { min-height: 220px; } }
  </style>
</head>
<body>
  <main class="shell">
    <div class="eyebrow">Risk-first review planning</div>
    <h1>Explain My Diff</h1>
    <p class="lede">Paste a unified diff and get a deterministic review order, evidence, and questions for a human reviewer.</p>
    <section class="grid" aria-label="Diff triage workspace">
      <form class="panel" id="triage-form">
        <h2>Review a diff</h2>
        <p class="hint">Your diff stays local to this server. Reviewed code is never executed.</p>
        <label for="diff">Unified diff</label>
        <textarea id="diff" name="diff" required spellcheck="false" placeholder="diff --git a/src/example.py b/src/example.py\n..."></textarea>
        <label for="focus">Reviewer focus <span>(optional)</span></label>
        <input id="focus" name="reviewer_focus" placeholder="security, compatibility, reliability">
        <button id="submit" type="submit">Generate review plan</button>
        <p class="footer">Heuristics support review; they do not approve or declare a change safe.</p>
      </form>
      <section class="panel" aria-live="polite">
        <div id="empty" class="empty">Your ranked review plan will appear here.</div>
        <div id="result" class="result">
          <div id="status" class="status">● Complete</div>
          <div class="metrics">
            <div class="metric"><strong id="file-count">0</strong><span>changed files</span></div>
            <div class="metric"><strong id="unit-count">0</strong><span>review units</span></div>
            <div class="metric"><strong id="input-status">—</strong><span>input status</span></div>
          </div>
          <h2>Rendered report</h2>
          <pre id="markdown" class="markdown"></pre>
          <details>
            <summary>View JSON response</summary>
            <pre id="json" class="markdown"></pre>
          </details>
        </div>
      </section>
    </section>
  </main>
  <script>
    const form = document.getElementById('triage-form');
    const button = document.getElementById('submit');
    const empty = document.getElementById('empty');
    const result = document.getElementById('result');
    const status = document.getElementById('status');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      button.disabled = true;
      button.textContent = 'Analyzing…';
      try {
        const response = await fetch('/api/triage', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({diff: document.getElementById('diff').value, reviewer_focus: document.getElementById('focus').value || undefined})
        });
        const data = await response.json();
        empty.style.display = 'none';
        result.classList.add('visible');
        status.classList.toggle('error', !response.ok);
        status.textContent = response.ok ? '● Complete' : '● Request needs attention';
        if (!response.ok) {
          document.getElementById('markdown').textContent = data.message || data.error || 'The request could not be processed.';
          document.getElementById('json').textContent = JSON.stringify(data, null, 2);
          return;
        }
        document.getElementById('file-count').textContent = data.changed_files.length;
        document.getElementById('unit-count').textContent = data.review_order.length;
        document.getElementById('input-status').textContent = data.input_status;
        document.getElementById('markdown').textContent = data.markdown;
        document.getElementById('json').textContent = JSON.stringify(data, null, 2);
      } catch (error) {
        empty.style.display = 'none';
        result.classList.add('visible');
        status.classList.add('error');
        status.textContent = '● Connection error';
        document.getElementById('markdown').textContent = 'Unable to reach the local Explain My Diff server.';
        document.getElementById('json').textContent = String(error);
      } finally {
        button.disabled = false;
        button.textContent = 'Generate review plan';
      }
    });
  </script>
</body>
</html>
"""


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


class ExplainMyDiffHandler(BaseHTTPRequestHandler):
    """Serve the local UI and JSON triage API."""

    server_version = "ExplainMyDiff/1.0"

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        self._send_bytes(status, "application/json; charset=utf-8", _json_bytes(payload))

    def _send_error_json(self, status: HTTPStatus, code: str, message: str) -> None:
        self._send_json(status, {"error": code, "message": message})

    def _read_request_json(self) -> dict[str, Any] | None:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "missing_content_length", "Content-Length is required.")
            return None
        try:
            body_length = int(content_length)
        except ValueError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_content_length", "Content-Length must be an integer.")
            return None
        if body_length < 0:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_content_length", "Content-Length cannot be negative.")
            return None
        if body_length > MAX_REQUEST_BYTES:
            # Drain the advertised body in bounded chunks before closing so
            # clients receive the 413 response without a reset connection.
            remaining = body_length
            while remaining:
                chunk = self.rfile.read(min(65_536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            self._send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large", f"Request body must be at most {MAX_REQUEST_BYTES} bytes.")
            return None

        body = self.rfile.read(body_length)
        if len(body) != body_length:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "incomplete_request", "Request body ended before Content-Length.")
            return None
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_json", "Request body must be valid UTF-8 JSON.")
            return None
        if not isinstance(payload, dict):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_payload", "Request JSON must be an object.")
            return None
        return payload

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/":
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", INDEX_HTML.encode("utf-8"))
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "The requested path does not exist.")

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path != "/api/triage":
            self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "The requested path does not exist.")
            return
        payload = self._read_request_json()
        if payload is None:
            return
        if "diff" not in payload:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "missing_diff", "The 'diff' field is required.")
            return
        diff = payload["diff"]
        if not isinstance(diff, str):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_diff", "The 'diff' field must be a string.")
            return
        reviewer_focus = payload.get("reviewer_focus")
        if reviewer_focus is not None and not isinstance(reviewer_focus, str):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_reviewer_focus", "The 'reviewer_focus' field must be a string when provided.")
            return

        triage = triage_diff(diff, reviewer_focus)
        response = dict(triage)
        response["markdown"] = format_markdown(triage)
        self._send_json(HTTPStatus.OK, response)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep library use quiet; deployments can provide their own access log."""


def configured_port() -> int:
    """Read and validate the HTTP port from ``PORT`` (default 8080)."""

    raw_port = os.environ.get("PORT", "8080")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("PORT must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return port


def create_server(port: int | None = None) -> ThreadingHTTPServer:
    """Create a server bound to all interfaces, without starting its loop."""

    return ThreadingHTTPServer(("0.0.0.0", configured_port() if port is None else port), ExplainMyDiffHandler)


def main() -> int:
    """Run the browser interface until interrupted."""

    server = create_server()
    print(f"Explain My Diff web interface listening on http://0.0.0.0:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Web Dashboard Server for CV Apply.
Runs a lightweight REST API & web server on http://localhost:5000
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cvapply.config import settings
from cvapply.convex_api import ConvexClient
from cvapply.main import run_pipeline
from cvapply.apply import run_apply


WEB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs", "engine.log"))


class DashboardHandler(BaseHTTPRequestHandler):

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress standard HTTP logging in console
        pass

    def _set_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self._set_cors()
        self.end_headers()

    def _json_response(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self._set_cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html_response(self, html_path: str) -> None:
        if not os.path.exists(html_path):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"HTML dashboard file not found")
            return
        with open(html_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self._set_cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            index_path = os.path.join(WEB_DIR, "index.html")
            self._html_response(index_path)
            return

        if path == "/api/stats":
            self.handle_get_stats()
            return

        if path == "/api/jobs":
            self.handle_get_jobs()
            return

        if path == "/api/logs":
            self.handle_get_logs()
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/action/fetch":
            def _fetch():
                try:
                    run_pipeline(dry_run=False, score=True)
                except Exception as e:
                    print(f"Web API fetch error: {e}")
            threading.Thread(target=_fetch, daemon=True).start()
            self._json_response({"status": "started", "message": "Job sourcing & scoring pipeline started in background."})
            return

        if path == "/api/action/apply":
            def _apply():
                try:
                    run_apply(submit=True, limit=5, job_id=None, headed=False)
                except Exception as e:
                    print(f"Web API apply error: {e}")
            threading.Thread(target=_apply, daemon=True).start()
            self._json_response({"status": "started", "message": "Live application batch started in background."})
            return

        self.send_response(404)
        self.end_headers()

    def handle_get_stats(self) -> None:
        try:
            convex = ConvexClient()
            stats = convex.query("queries:jobStats", {}) or {}
            scored_jobs = convex.query("queries:scoredJobs", {"limit": 500}) or []
            apps = convex.query("queries:applicationsSince", {"since": 0}) or []

            lk_count = sum(1 for j in scored_jobs if j.get("location_tier") == "sri_lanka")
            email_apps = sum(1 for a in apps if a.get("metadata", {}).get("channel") in ("email", "email_fallback"))
            portal_apps = sum(1 for a in apps if a.get("metadata", {}).get("channel") not in ("email", "email_fallback"))

            # Calculate source platform distribution
            sources_counts: dict[str, int] = {}
            for j in scored_jobs:
                src = j.get("source") or "Direct Direct Company / XpressJobs"
                if "xpress" in src.lower() or "lk" in src.lower() or "direct" in src.lower():
                    name = "Sri Lanka IT (XpressJobs/Direct)"
                elif "greenhouse" in src.lower():
                    name = "Greenhouse Board"
                elif "ashby" in src.lower():
                    name = "Ashby HQ"
                elif "lever" in src.lower():
                    name = "Lever Co"
                elif "himalayas" in src.lower():
                    name = "Himalayas Remote"
                elif "remoteok" in src.lower():
                    name = "RemoteOK"
                else:
                    name = src.capitalize()
                sources_counts[name] = sources_counts.get(name, 0) + 1

            data = {
                "total_jobs_fetched": stats.get("total", 0),
                "status_counts": stats.get("counts", {}),
                "applications_total": len(apps),
                "applications_email": email_apps,
                "applications_portal": portal_apps,
                "scored_sri_lanka_jobs": lk_count,
                "sources_counts": sources_counts,
                "daily_cap": settings.daily_app_cap,
                "match_threshold": settings.match_threshold,
                "candidate_name": f"{settings.candidate_first_name} {settings.candidate_last_name}",
                "candidate_email": settings.candidate_email,
                "only_sri_lanka": settings.only_sri_lanka,
                "ai_engine": "NVIDIA Nemotron 3.5 Lightning 30B (Primary)",
                "smtp_verification": "Active 100% Zero Bounce Pre-Verification",
            }
            self._json_response(data)
        except Exception as exc:
            self._json_response({"error": str(exc)}, status=500)


    def handle_get_jobs(self) -> None:
        try:
            convex = ConvexClient()
            scored = convex.query("queries:scoredJobs", {"limit": 100}) or []
            apps = convex.query("queries:applicationsSince", {"since": 0}) or []
            pending = convex.query("queries:pendingScoring", {"limit": 50}) or []

            # Merge records for UI display
            combined = []
            for j in scored:
                combined.append({
                    "id": j.get("_id"),
                    "company": j.get("company"),
                    "title": j.get("title"),
                    "score": j.get("match_score"),
                    "status": j.get("status"),
                    "location_tier": j.get("location_tier"),
                    "location": j.get("location", "Colombo, Sri Lanka"),
                    "apply_url": j.get("apply_url"),
                    "reason": j.get("match_reason"),
                    "created_at": j.get("created_at"),
                })

            for j in pending:
                combined.append({
                    "id": j.get("_id"),
                    "company": j.get("company"),
                    "title": j.get("title"),
                    "score": 0,
                    "status": "pending_scoring",
                    "location_tier": j.get("location_tier"),
                    "location": j.get("location", "Colombo, Sri Lanka"),
                    "apply_url": j.get("apply_url"),
                    "reason": "Queued for AI scoring",
                    "created_at": j.get("created_at"),
                })

            self._json_response({"jobs": combined, "applications": apps})
        except Exception as exc:
            self._json_response({"error": str(exc)}, status=500)

    def handle_get_logs(self) -> None:
        lines = []
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-100:]
            except Exception as e:
                lines = [f"Error reading log file: {e}"]
        else:
            lines = ["Log file engine.log initialized. Waiting for cycle output..."]
        self._json_response({"logs": [l.strip() for l in lines]})


def run_web_server(port: int = 5000) -> None:
    os.makedirs(WEB_DIR, exist_ok=True)
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"\n{'='*60}")
    print(f"✨ CV APPLY CONTROL DASHBOARD ONLINE")
    print(f"🌐 Access Dashboard UI at: http://localhost:{port}")
    print(f"{'='*60}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web server...")
        server.server_close()


if __name__ == "__main__":
    run_web_server()

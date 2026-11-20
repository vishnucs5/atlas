"""Unified supervisor to run ATLAS Cloud Stack (API server + Worker daemon).

Connects to Supabase managed PostgreSQL via ATLAS_DATABASE_URL (or falls back
to local SQLite WAL if unspecified), starts the FastAPI control plane and
distributed worker daemon, and performs automated health probes.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def probe_endpoint(url: str, timeout: float = 3.0) -> bool:
    """Check whether HTTP endpoint responds with 200 OK."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ATLAS-CloudStack-Supervisor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="ATLAS Cloud Stack Supervisor")
    parser.add_argument("--port", type=int, default=8000, help="FastAPI port (default: 8000)")
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="FastAPI host (default: 127.0.0.1)"
    )
    parser.add_argument("--no-worker", action="store_true", help="Run only the API service")
    parser.add_argument("--verify-only", action="store_true", help="Probe running stack and exit")
    args = parser.parse_args()

    health_url = f"http://{args.host}:{args.port}/healthz"
    ready_url = f"http://{args.host}:{args.port}/readyz"

    if args.verify_only:
        print(f"[*] Probing ATLAS API at {health_url}...")
        is_healthy = probe_endpoint(health_url)
        is_ready = probe_endpoint(ready_url)
        print(f"[*] Healthz: {'UP' if is_healthy else 'DOWN'}")
        print(f"[*] Readyz:  {'UP' if is_ready else 'DOWN'}")
        return 0 if (is_healthy and is_ready) else 1

    repo_root = Path(__file__).resolve().parent.parent
    db_url = os.environ.get("ATLAS_DATABASE_URL")

    print("=================================================================")
    print("           ATLAS CLOUD RUNTIME SUPERVISOR                        ")
    print("=================================================================")
    if db_url:
        masked_db = db_url.rsplit("@", 1)[-1] if "@" in db_url else "[configured]"
        print(f"[*] Backend Database: PostgreSQL (Supabase: {masked_db})")
    else:
        print("[*] Backend Database: Local SQLite WAL (.atlas/sessions.db)")
    print(f"[*] API Target:       http://{args.host}:{args.port}")
    print(f"[*] Worker Daemon:    {'Disabled' if args.no_worker else 'Enabled'}")
    print("=================================================================")

    processes: list[subprocess.Popen] = []

    def shutdown(sig, frame):
        print("\n[*] Shutting down ATLAS Cloud Stack services...")
        for p in processes:
            try:
                p.terminate()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 1. Start API Server
    api_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "atlas_api.main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--log-level",
        "info",
    ]
    print(f"[*] Launching API Server: {' '.join(api_cmd)}")
    api_proc = subprocess.Popen(api_cmd, cwd=repo_root)
    processes.append(api_proc)

    # 2. Wait for API to become ready
    print("[*] Waiting for API server readiness...")
    ready = False
    for _attempt in range(1, 20):
        time.sleep(0.5)
        if probe_endpoint(ready_url):
            ready = True
            print(f"[+] API is READY at http://{args.host}:{args.port}/readyz")
            break
        if api_proc.poll() is not None:
            print("[-] API server process exited prematurely.", file=sys.stderr)
            return 1

    if not ready:
        print("[-] API server readiness probe timed out.", file=sys.stderr)
        api_proc.terminate()
        return 1

    # 3. Start Background Worker Daemon
    if not args.no_worker:
        worker_cmd = [
            sys.executable,
            "-m",
            "atlas_cli.main",
            "worker",
            "--heartbeat",
            "5.0",
        ]
        print(f"[*] Launching Worker Daemon: {' '.join(worker_cmd)}")
        worker_proc = subprocess.Popen(worker_cmd, cwd=repo_root)
        processes.append(worker_proc)

    print("\n[+] ATLAS Cloud Stack is fully operational.")
    print("    Press Ctrl+C to stop services.\n")

    # Monitor processes
    try:
        while True:
            for p in processes:
                code = p.poll()
                if code is not None:
                    print(f"[-] Process {p.pid} terminated with code {code}.")
                    shutdown(None, None)
            time.sleep(1.0)
    except KeyboardInterrupt:
        shutdown(None, None)

    return 0


if __name__ == "__main__":
    sys.exit(main())

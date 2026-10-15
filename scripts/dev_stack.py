"""Run the whole app locally with one command.

    uv run python scripts/dev_stack.py           Postgres, S3 stand-in, API + workers, frontend
    uv run python scripts/dev_stack.py --fresh   same, starting from an empty database
    uv run python scripts/dev_stack.py --mock    frontend only, with simulated data

Nothing here touches hosted services: Postgres is embedded (pgserver, data in
.dev-stack/), uploads go to a local S3 stand-in (moto) instead of R2, and the
API runs the import and enrichment workers in-process like on Render. Use
--database-url to point at your own Postgres (e.g. Docker) instead.

Requires uv and Node.js 22. The first run downloads Python 3.12 and the
service packages into uv's cache. Stop everything with Ctrl+C.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "Frontend"
STATE_DIR = REPO / ".dev-stack"
SERVICES_SCRIPT = Path(__file__).resolve().parent / "dev_stack_services.py"
# pgserver only has wheels up to Python 3.12; pinned so every run reuses the
# same cached environment.
SERVICES_ENV = [
    "--no-project",
    "--python",
    "3.12",
    "--with",
    "pgserver==0.1.4",
    "--with",
    "tzdata==2026.5",
    "--with",
    "moto[server]==5.2.4",
]
DATABASE_NAME = "ldihk_dev"
BUCKET = "ldihk-uploads"
# Fake credentials for the local S3 stand-in only.
S3_KEY_ID = "dev-stack-key"
S3_SECRET = "dev-stack-secret"
IS_WINDOWS = os.name == "nt"


class Service:
    """A child process whose output is prefixed and can be waited on."""

    def __init__(self, name: str, args: list[str], *, env=None, cwd=None, keep_stdin: bool = False):
        self.name = name
        self._lines: queue.Queue[str] = queue.Queue()
        self.process = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if keep_stdin else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # Our own Ctrl+C handling stops services in order.
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
            start_new_session=not IS_WINDOWS,
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._lines.put(line)
            try:
                print(f"[{self.name}] {line}", end="", flush=True)
            except (OSError, ValueError):
                pass  # keep draining, or the child blocks on a full pipe

    def wait_for_line(self, pattern: str, timeout: float) -> re.Match[str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self._lines.get(timeout=0.5)
            except queue.Empty:
                if self.process.poll() is not None:
                    raise SystemExit(f"{self.name} exited with code {self.process.returncode}")
                continue
            if match := re.search(pattern, line):
                return match
        raise SystemExit(f"{self.name} did not become ready within {timeout:.0f} s")

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        if self.process.stdin is not None:
            # Every service shuts down cleanly when its stdin closes.
            try:
                self.process.stdin.close()
                self.process.wait(timeout=30)
                return
            except (OSError, subprocess.TimeoutExpired):
                pass
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()


def main() -> int:
    args = _parse_args()
    # Service output may contain characters the console encoding lacks.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    # Treat Ctrl+Break / SIGTERM like Ctrl+C, so services stop in order.
    signal.signal(signal.SIGBREAK if IS_WINDOWS else signal.SIGTERM, _interrupt)
    _require_tool("npm", "Install Node.js 22 (https://nodejs.org).")
    _ensure_frontend_dependencies()
    for port in (args.frontend_port,) if args.mock else (args.frontend_port, args.backend_port, args.storage_port):
        _require_free_port(port)

    services: list[Service] = []
    try:
        if args.mock:
            services.append(_start_frontend(args, mock=True))
        else:
            uv = _require_tool("uv", "Install uv (https://docs.astral.sh/uv/).")
            database_url = _start_database(args, uv, services)
            services.append(_start_storage(args, uv))
            services.append(_start_backend(args, database_url))
            _wait_for_http(f"http://127.0.0.1:{args.backend_port}/health", "api", services[-1], 60)
            services.append(_start_frontend(args, mock=False))
        _wait_for_http(f"http://localhost:{args.frontend_port}/", "web", services[-1], 180)
        _print_summary(args)
        while all(service.process.poll() is None for service in services):
            time.sleep(0.5)
        crashed = next(service for service in services if service.process.poll() is not None)
        print(f"\n{crashed.name} exited with code {crashed.process.returncode}; stopping the stack.")
        return 1
    except KeyboardInterrupt:
        print("\nStopping the stack...")
        return 0
    finally:
        for service in reversed(services):
            service.stop()


def _interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


def _guarded(command: list[str]) -> list[str]:
    """Run command so that it dies with the stack (see dev_stack_services.py)."""
    return [sys.executable, str(SERVICES_SCRIPT), "guard", "--", *command]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true", help="frontend only, with simulated data")
    parser.add_argument("--fresh", action="store_true", help="drop and recreate the local database first")
    parser.add_argument("--database-url", help="use this Postgres instead of the embedded one")
    parser.add_argument("--profiles", type=int, default=30, help="synthetic population size to seed (default 30)")
    parser.add_argument("--days", type=int, default=28, help="days of synthetic history to seed (default 28)")
    parser.add_argument("--frontend-port", type=int, default=4321)
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--storage-port", type=int, default=5055)
    args = parser.parse_args()
    if args.fresh and args.database_url:
        parser.error("--fresh only applies to the embedded database; reset your own database yourself")
    return args


def _start_database(args: argparse.Namespace, uv: str, services: list[Service]) -> str:
    if args.database_url:
        database_url = args.database_url
    else:
        postgres = Service(
            "db",
            [uv, "run", *SERVICES_ENV, "python", str(SERVICES_SCRIPT), "postgres", str(STATE_DIR / "pgdata")],
            cwd=REPO,
            keep_stdin=True,
        )
        services.append(postgres)
        admin_url = postgres.wait_for_line(r"READY (\S+)", timeout=600).group(1)
        database_url = _create_database(admin_url, fresh=args.fresh)
    _migrate_and_seed(database_url, profiles=args.profiles, days=args.days)
    return database_url


def _create_database(admin_url: str, *, fresh: bool) -> str:
    import psycopg

    with psycopg.connect(admin_url, autocommit=True) as admin:
        if fresh:
            admin.execute(f'DROP DATABASE IF EXISTS "{DATABASE_NAME}" WITH (FORCE)')
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE_NAME,)).fetchone()
        if not exists:
            admin.execute(f'CREATE DATABASE "{DATABASE_NAME}"')
    return urlunsplit(urlsplit(admin_url)._replace(path=f"/{DATABASE_NAME}"))


def _migrate_and_seed(database_url: str, *, profiles: int, days: int) -> None:
    sys.path.insert(0, str(REPO))
    os.environ["DATABASE_URL"] = database_url
    from backend import db

    applied = db.run_migrations()
    print(f"[db] migrations up to date ({len(applied)} applied now)")
    with db.connect() as connection:
        synthetic_users = connection.execute("SELECT count(*) FROM users WHERE is_synthetic = true").fetchone()[0]
    if synthetic_users or profiles <= 0:
        return
    from backend.scripts.seed_synthetic_usage import seed_synthetic_usage

    print(f"[db] seeding {profiles} synthetic profiles over {days} days (population benchmark)...")
    seed_synthetic_usage(
        total_profiles=profiles,
        total_days=days,
        seed_run_name="dev-stack",
        random_seed=7,
        run_schema_migrations=False,
    )


def _start_storage(args: argparse.Namespace, uv: str) -> Service:
    origins = [f"http://localhost:{args.frontend_port}", f"http://127.0.0.1:{args.frontend_port}"]
    storage = Service(
        "s3",
        [uv, "run", *SERVICES_ENV, "python", str(SERVICES_SCRIPT), "storage", str(args.storage_port), BUCKET, *origins],
        cwd=REPO,
        keep_stdin=True,
    )
    storage.wait_for_line(r"READY", timeout=600)
    return storage


def _start_backend(args: argparse.Namespace, database_url: str) -> Service:
    env = dict(
        os.environ,
        PYTHONPATH=str(REPO),
        PYTHONUNBUFFERED="1",
        DATABASE_URL=database_url,
        FRONTEND_ALLOWED_ORIGINS=f"http://localhost:{args.frontend_port}",
        ENABLE_LOCAL_FILE_ROUTES="false",
        RUN_WORKERS_IN_PROCESS="true",
        WORKER_POLL_INTERVAL_SECONDS="2",
        S3_ENDPOINT_URL=f"http://127.0.0.1:{args.storage_port}",
        S3_BUCKET=BUCKET,
        AWS_ACCESS_KEY_ID=S3_KEY_ID,
        AWS_SECRET_ACCESS_KEY=S3_SECRET,
        AWS_REGION="us-east-1",
    )
    env.setdefault("LOG_LEVEL", "INFO")
    code = (
        "from backend.app import create_app; "
        f"create_app().run(host='127.0.0.1', port={args.backend_port}, threaded=True)"
    )
    return Service("api", _guarded([sys.executable, "-c", code]), cwd=REPO, env=env, keep_stdin=True)


def _start_frontend(args: argparse.Namespace, *, mock: bool) -> Service:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("CUSTOM_AWS_", "S3_"))}
    if mock:
        env.update(PUBLIC_API_URL="", PUBLIC_MOCK_API="true")
    else:
        env.update(
            PUBLIC_API_URL=f"http://127.0.0.1:{args.backend_port}",
            PUBLIC_MOCK_API="false",
            CUSTOM_AWS_ACCESS_KEY_ID=S3_KEY_ID,
            CUSTOM_AWS_SECRET_ACCESS_KEY=S3_SECRET,
            CUSTOM_AWS_REGION="us-east-1",
            S3_BUCKET=BUCKET,
            S3_ENDPOINT_URL=f"http://127.0.0.1:{args.storage_port}",
        )
    npm = shutil.which("npm")
    assert npm is not None
    return Service(
        "web",
        _guarded([npm, "run", "dev", "--", "--host", "localhost", "--port", str(args.frontend_port)]),
        cwd=FRONTEND,
        env=env,
        keep_stdin=True,
    )


def _ensure_frontend_dependencies() -> None:
    if (FRONTEND / "node_modules" / ".package-lock.json").exists():
        return
    print("[web] installing frontend dependencies (npm ci)...")
    npm = shutil.which("npm")
    assert npm is not None
    subprocess.run([npm, "ci"], cwd=FRONTEND, check=True)


def _wait_for_http(url: str, name: str, service: Service, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service.process.poll() is not None:
            raise SystemExit(f"{name} exited with code {service.process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=5):
                return
        except urllib.error.HTTPError:
            return  # it answered
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    raise SystemExit(f"{name} did not answer on {url} within {timeout:.0f} s")


def _require_tool(name: str, hint: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"{name} was not found on PATH. {hint}")
    return path


def _require_free_port(port: int) -> None:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"Port {port} is already in use. Stop whatever runs there or pick another port.")


def _print_summary(args: argparse.Namespace) -> None:
    lines = [
        "",
        "  LDiHK local stack is running" + (" (mock data)" if args.mock else ""),
        f"  App:      http://localhost:{args.frontend_port}/",
    ]
    if not args.mock:
        lines += [
            f"  API:      http://127.0.0.1:{args.backend_port}/health",
            f"  Storage:  http://127.0.0.1:{args.storage_port}/ (bucket {BUCKET})",
            "  Upload a Takeout ZIP in the app; the import runs in the API process.",
        ]
    lines += ["  Press Ctrl+C to stop.", ""]
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

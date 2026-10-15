"""Local stand-ins for the hosted services, started by scripts/dev_stack.py.

    postgres <data-dir>                     embedded Postgres (pgserver)
    storage <port> <bucket> <origin>...     S3-compatible storage (moto), like R2
    guard -- <command>...                   run a command, kill its process tree on exit

postgres and storage run in a separate Python 3.12 environment (pgserver has
no newer wheels), which dev_stack.py creates with `uv run --with`; they print
one "READY ..." line. Every mode runs until its stdin closes, so the services
stop with the stack even if the stack itself is killed.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


def _wait_for_stdin_close() -> None:
    try:
        while sys.stdin.readline():
            pass
    except (KeyboardInterrupt, OSError):
        pass


def run_postgres(data_dir: str) -> None:
    import pgserver
    import tzdata
    from pgserver.postgres_server import PostgresServer
    from pgserver.utils import PostmasterInfo

    # Some pgserver builds ship without time zone data, so Postgres would
    # reject every IANA zone name the frontend sends.
    timezone_dir = Path(pgserver.__file__).parent / "pginstall" / "share" / "postgresql" / "timezone"
    if not (timezone_dir / "Europe" / "Berlin").exists():
        shutil.copytree(Path(tzdata.__file__).parent / "zoneinfo", timezone_dir, dirs_exist_ok=True)

    pgdata = Path(data_dir).resolve()
    pgdata.mkdir(parents=True, exist_ok=True)
    # A server left running by a killed stack may be unusable (on Windows its
    # child processes fail once the console that started it is gone). The
    # stack owns this data directory, so always start from a fresh server.
    _stop_postgres(pgdata)
    try:
        server = pgserver.get_server(pgdata, cleanup_mode="stop")
    except (subprocess.TimeoutExpired, AssertionError):
        # After an unclean stop, crash recovery can outlast pgserver's 10 s
        # start timeout (on Windows it waits for pgserver's own log file).
        # Postgres keeps starting: wait until it is ready, then attach again.
        print("Postgres is recovering from an unclean stop; waiting...", flush=True)
        PostgresServer._instances.pop(pgdata, None)
        deadline = time.monotonic() + 180
        while (info := PostmasterInfo.read_from_pgdata(pgdata)) is None or info.status != "ready":
            if time.monotonic() > deadline:
                raise SystemExit(f"Postgres did not become ready; see {pgdata / 'log'}")
            time.sleep(1)
        server = pgserver.get_server(pgdata, cleanup_mode="stop")
    print(f"READY {server.get_uri()}", flush=True)
    _wait_for_stdin_close()
    server.cleanup()
    # pgserver only stops the server once no other handle is left, and handles
    # of killed helpers stay listed forever, so stop it explicitly.
    _stop_postgres(pgdata)


def _stop_postgres(pgdata: Path) -> None:
    """Stop the server on pgdata if one runs, and reset pgserver's handle list."""
    import pgserver

    pg_ctl = Path(pgserver.__file__).parent / "pginstall" / "bin" / ("pg_ctl.exe" if os.name == "nt" else "pg_ctl")
    if (pgdata / "postmaster.pid").exists():
        subprocess.run(
            [str(pg_ctl), "stop", "-D", str(pgdata), "-m", "fast", "-w"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    (pgdata / ".handle_pids.json").unlink(missing_ok=True)


def run_storage(port: str, bucket: str, origins: list[str]) -> None:
    import boto3
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=int(port))
    server.start()
    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://127.0.0.1:{port}",
        region_name="us-east-1",
        aws_access_key_id="dev-stack-key",
        aws_secret_access_key="dev-stack-secret",
    )
    s3.create_bucket(Bucket=bucket)
    # The browser uploads straight to storage with a presigned PUT.
    s3.put_bucket_cors(
        Bucket=bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": origins,
                    "AllowedMethods": ["PUT"],
                    "AllowedHeaders": ["content-type"],
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        },
    )
    print(f"READY http://127.0.0.1:{port}", flush=True)
    stopper = threading.Thread(target=_wait_for_stdin_close)
    stopper.start()
    stopper.join()
    server.stop()


def run_guard(command: list[str]) -> int:
    """Run command until it exits or our stdin closes (then kill its tree)."""
    child = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )

    def stop_child_when_stdin_closes() -> None:
        _wait_for_stdin_close()
        if child.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    threading.Thread(target=stop_child_when_stdin_closes, daemon=True).start()
    return child.wait()


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "guard" and argv[1] == "--":
        return run_guard(argv[2:])
    if len(argv) == 2 and argv[0] == "postgres":
        run_postgres(argv[1])
    elif len(argv) >= 4 and argv[0] == "storage":
        run_storage(argv[1], argv[2], argv[3:])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

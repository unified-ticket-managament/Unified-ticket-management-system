# sla_sweep_local_loop.py
#
# Local-dev-only stand-in for the Render Cron Job that hits
# POST /internal/sla/sweep once a minute in production (see
# sla_sweep_ping.py, the actual cron entrypoint). Nothing triggers the
# sweep locally otherwise, which made response-SLA breach notifications
# look "not working" when testing via Swagger — a still-PENDING clock
# that never gets a sweep tick never gets checked at all (separately
# from the completion-time breach check in sla_service.py, which only
# fires when a clock is completed, not while it's still sitting idle).
#
# Not wired into scripts/start.sh unconditionally — that script is also
# Render's own startCommand for the real backend, which already has its
# own cron hitting this same endpoint. Opt in locally via
# ENABLE_LOCAL_SLA_SWEEP_LOOP=true in unified-backend/.env; never set
# that in Render's env vars.
#
# Reads unified-backend/.env directly (via python-dotenv, already a
# dependency here) so it works standalone — `python
# scripts/sla_sweep_local_loop.py` — without needing every var
# re-exported into the shell first.

import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_INTERVAL_SECONDS = 30


def run_once(url: str, secret: str) -> bool:
    try:
        response = requests.post(
            url,
            headers={"X-SLA-Sweep-Secret": secret},
            timeout=45,
        )
    except requests.RequestException as exc:
        print(f"POST {url} failed: {exc}")
        return False

    print(f"POST {url} -> {response.status_code} {response.text}")
    return response.ok


def main() -> int:
    port = os.environ.get("PORT", "8000")
    url = os.environ.get("SLA_SWEEP_URL", f"http://localhost:{port}/internal/sla/sweep")
    secret = os.environ.get("SLA_SWEEP_SHARED_SECRET")
    interval = float(
        os.environ.get("SLA_SWEEP_LOCAL_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)
    )

    if not secret:
        print(
            "SLA_SWEEP_SHARED_SECRET is not set (checked process env and .env) — "
            "can't call the sweep endpoint without it."
        )
        return 1

    print(f"Local SLA sweep loop: POSTing {url} every {interval}s. Ctrl+C to stop.")

    while True:
        run_once(url, secret)
        time.sleep(interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)

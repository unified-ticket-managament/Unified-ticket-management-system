# sla_sweep_ping.py
#
# The Render Cron Job's entrypoint — a minimal script (only needs
# `requests`, not the full backend's dependency tree, so the cron
# job's own build stays a lightweight `pip install requests` rather
# than a second full `pip install -r requirements.txt`) that POSTs to
# this backend's POST /internal/sla/sweep with the shared secret.
#
# Required env vars: SLA_SWEEP_URL (the deployed unified-backend's
# root + /internal/sla/sweep), SLA_SWEEP_SHARED_SECRET (must match
# unified-backend's own setting of the same name exactly).
#
# Exits non-zero on any non-2xx response so Render's own cron run
# history surfaces failures instead of silently looking green.

import os
import sys

import requests


def main() -> int:
    url = os.environ["SLA_SWEEP_URL"]
    secret = os.environ["SLA_SWEEP_SHARED_SECRET"]

    # Cadence tightened to every minute and the sweep now resolves more
    # per-clock recipients (Team Lead + team members, assigned-agent
    # lookups, a new HALF_ELAPSED tier) — 45s leaves real headroom
    # under that 60s schedule instead of the old 30s value.
    response = requests.post(
        url,
        headers={"X-SLA-Sweep-Secret": secret},
        timeout=45,
    )

    print(f"POST {url} -> {response.status_code}")
    print(response.text)

    if not response.ok:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

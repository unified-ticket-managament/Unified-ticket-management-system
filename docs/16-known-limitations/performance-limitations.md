# Performance Limitations

## Connection pool sized for a single frontend bug, not arbitrary scale

**Limitation**: `unified-backend/app/database/session.py`'s pool (`pool_size=20, max_overflow=30, pool_timeout=10` at time of writing) was raised specifically in response to a frontend request-duplication bug that put 200-300 concurrent requests in flight. It is headroom against a repeat of that specific class of incident, not a number derived from a real production-scale capacity plan.
**Impact**: A future traffic spike of a different shape could still exhaust the pool; requests then fail fast (10s timeout) rather than queuing indefinitely (the old, worse behavior).
**Why It Exists**: Reactive fix to a real incident, not proactive capacity planning.
**Current Workaround**: `pool_timeout=10` ensures fast, clear failure instead of ~30s hangs.
**Is It Planned?**: Raising it further requires checking Neon's own connection ceiling first — explicitly called out as a prerequisite, not done preemptively.

## SLA sweep interval is tuned for dev iteration speed, not production load

**Limitation**: The local-dev default sweep interval is 10 seconds (`SLA_SWEEP_INTERVAL_SECONDS`); production (`render.yaml`) is explicitly overridden to 60 seconds. These are two deliberately different cadences, not a shared constant.
**Impact**: Local behavior (SLA state changes visible within ~10s) does not represent production timing (~60s) — don't extrapolate perceived "real-time-ness" from local testing to production.
**Why It Exists**: Fast local feedback loop vs. lower steady-state DB load in production.
**Current Workaround**: None needed; just don't confuse the two environments' cadence.
**Is It Planned?**: No.

## A corrupted `ticket_type` used to fail an entire sweep tick

**Limitation** (historical, now fixed at the specific root cause found): a ticket with a `ticket_type` value not matching any real `CategoryName` crashed the whole sweep — not just that ticket — due to an unvalidated raw string compared against a Postgres-native enum column, and the per-ticket `SAVEPOINT` isolation was found **not** to fully protect against this specific error class (it cascaded into a `MissingGreenlet` error on a later, unrelated ticket in the same tick). Fixed by validating `category_name` against known `CategoryName` values in Python before the query reaches Postgres, in the two `UserRepository` methods this affected.
**Impact**: This specific failure mode is fixed; the broader lesson (SAVEPOINT isolation isn't a universal guarantee against every Postgres error class) is worth remembering when adding new per-ticket sweep logic.
**Why It Exists**: Historical bug, root-caused and closed.
**Current Workaround**: N/A — fixed.
**Is It Planned?**: N/A — already resolved; documented here as a cautionary precedent, not an open item.

## No caching/pagination performance data captured

**Limitation**: No load-testing results, query-plan analysis, or documented p95/p99 latency figures were found anywhere in the repository.
**Impact**: Performance characteristics beyond what's described above (pool sizing, sweep cadence) are **not confirmed** — do not assume the system has been load-tested at any particular scale.
**Why It Exists**: Not done as of this writing.
**Current Workaround**: N/A.
**Is It Planned?**: Not confirmed.

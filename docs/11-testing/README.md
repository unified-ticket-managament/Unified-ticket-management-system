# Testing

- [testing-strategy.md](testing-strategy.md) — what's actually tested, and the overall shape
- [unit-testing.md](unit-testing.md) — pure-logic tests, no database
- [integration-testing.md](integration-testing.md) — DB-touching tests and their known constraints
- [api-testing.md](api-testing.md) — what exists at the HTTP/route level
- [workflow-testing.md](workflow-testing.md) — end-to-end business-workflow coverage
- [regression-testing.md](regression-testing.md) — tests that exist specifically because a real bug happened once
- [production-smoke-tests.md](production-smoke-tests.md) — what to check after a deploy (no automated smoke-test suite exists)

## Headline facts (confirmed by direct inspection)

- **Backend** (`unified-backend/tests/`): 48 test files as of the 2026-08-21 client-filters/OTP-classifier commit (46 at the prior documentation pass, plus `test_otp_classifier.py` and `test_email_service_otp_sla_completion.py`), `pytest`/`pytest-asyncio`, `asyncio_mode = auto` (the entirety of `pytest.ini`).
- **Frontend** (`unified-frontend/`, `ticketing-service/frontend/`): **no test files or test framework configuration exist at all.** `npx tsc --noEmit` is the only correctness gate.
- **`shared_models/tests/`**: one trivial import-smoke test.
- **`.deepeval/`**: an empty scaffold directory — not a functioning LLM-eval setup.
- **Three specific backend test files hang if run together in the same pytest process** (a pre-existing `pytest-asyncio` event-loop-scope issue, not a bug in the tests themselves) — see [integration-testing.md](integration-testing.md).

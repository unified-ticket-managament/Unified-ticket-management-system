# Unit Testing

Pure-logic tests — fake/in-memory repositories, no real database connection — safe to run together in any order or combination.

## Representative files

| File | Tests | Focus |
|---|---|---|
| `test_sla_clock_math.py` | 30 | Due-date math — pause/resume shifts, priority up/downgrade recompute. The largest pure-logic file, and the most heavily tested single calculation in the codebase. |
| `test_escalation_rules.py` | 12 | Assignment-chain-climbing rules for escalation target resolution |
| `test_sla_escalation_rules.py` | 27 | Escalation recipient resolution by claim state/category |
| `test_rule_conditions.py` | 13 | Mail rule condition evaluators (equals/contains/AND, case sensitivity) |
| `test_notification_email_dispatch.py` | 15 | Which notification types trigger an email, recipient correctness, failure isolation — deliberately avoids the DB-touching event-loop hang by using the same fake-repository convention as `test_email_service_client_matching.py` |
| `test_compose_signature.py` | 5 | Agent email signature building |
| `test_email_envelope.py` | 8 | Reply/compose envelope construction |
| `test_undo_send.py` | 10 | Undo-send cancel window, idempotency, authorization |
| `test_otp_classifier.py` | — | The semantic OTP classifier alone (`otp_classifier.py`) — genuine-OTP and support-request-mentioning-OTP examples, a bare "OTP" mention staying under threshold, numbers-alone staying under threshold, the threshold itself behaving as a real parameter. Added 2026-08-21. |
| `test_email_service_otp_sla_completion.py` | — | `EmailService.receive_email`'s classifier wiring — completes with no rule engine configured at all, completes strictly before the rule engine call runs, stays completed even if the rule engine subsequently raises, and a support-request/normal email never triggers completion. Added 2026-08-21. |

## Convention

Pure-logic tests in this suite consistently use a **fake-repository pattern** (hand-written stand-ins implementing the same interface as the real repository) rather than mocking at the ORM/SQL level — this is what lets them run without a database connection and avoid the event-loop-scope hang entirely.

## Running just the safe subset

There is no explicit pytest marker separating pure-logic from DB-touching tests (`pytest.ini` declares no markers at all) — the split described here is inferred from each file's own implementation, not enforced by tooling. A future improvement would be adding a `@pytest.mark.db` marker to the known DB-touching files (see [integration-testing.md](integration-testing.md)) so `pytest -m "not db"` could run the safe subset in one invocation without manual file-by-file selection.

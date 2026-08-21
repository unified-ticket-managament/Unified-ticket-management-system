# Data Flow

## Request/response (authenticated API call)

```mermaid
sequenceDiagram
    participant Browser
    participant FE as unified-frontend (Next.js)
    participant BE as unified-backend (FastAPI)
    participant Cache as rbac_cache (in-memory TTL)
    participant DB as PostgreSQL (Neon)

    Browser->>FE: user action
    FE->>BE: HTTPS request, Authorization: Bearer <JWT>
    BE->>BE: decode JWT (app/auth/jwt.py)
    BE->>Cache: is_valid(user_id, permission_version)?
    alt cache hit
        Cache-->>BE: valid — reconstruct transient User from claims
    else cache miss
        BE->>DB: UserRepository.get_by_id (joinedload role+category)
        DB-->>BE: real, session-attached User row
        BE->>Cache: mark_valid(...)
    end
    BE->>BE: route handler -> service -> repository
    BE->>DB: business query/mutation
    DB-->>BE: result
    BE-->>FE: JSON response (+ Server-Timing header)
    FE-->>Browser: render
```

## Inbound email → ticket (the core business flow)

```mermaid
sequenceDiagram
    participant Graph as Microsoft Graph
    participant Poller as graph_mail_poller / webhook receiver
    participant Rules as RuleEngineService
    participant Email as EmailService.receive_email
    participant SLA as SLAService
    participant DB as PostgreSQL

    Graph->>Poller: new message (webhook push or poll)
    Poller->>Email: mapped EmailRequest (mail_mapping_service)
    Email->>DB: dedupe by message_id
    Email->>DB: resolve Client (sender/recipient match)
    Email->>DB: thread detection (In-Reply-To/References)
    Email->>DB: create Interaction row
    Email->>Rules: evaluate_and_execute_for_email (Mail Rules, then OTP Rules)
    alt OTP rule matched
        Rules->>SLA: complete_first_response_clock(reason="OTP_RECOGNIZED")
    end
    Email->>DB: create/init FirstResponseSLA clock (if new thread root)
    Email-->>Poller: commit (same transaction as rule evaluation)
```

Full narrative, business rules, and edge cases: [03-business-workflows/communication](../03-business-workflows/communication/).

## SLA sweep tick

```mermaid
sequenceDiagram
    participant Sched as APScheduler (in-process)
    participant Sweep as SLASweepService.run_sweep
    participant Notif as NotificationService
    participant Esc as EscalationService

    Sched->>Sweep: fire every SLA_SWEEP_INTERVAL_SECONDS
    Sweep->>Sweep: load every active First Response + Resolution clock
    loop each clock
        Sweep->>Sweep: compute elapsed fraction vs. thresholds
        alt new threshold crossed
            Sweep->>Sweep: SLABreachNotificationRepository.try_record_many (idempotent)
            Sweep->>Notif: notify() — bell + SSE + conditional email
        end
    end
    Sweep->>Esc: evaluate_overdue (ack-window auto-advance)
    Sweep->>Esc: EscalationHandlingSlaService.evaluate_breaches
```

Full detail: [03-business-workflows/sla](../03-business-workflows/sla/) and [03-business-workflows/escalation](../03-business-workflows/escalation/).

## Notification fan-out

```mermaid
flowchart LR
    TRIGGER[~17 call sites across app.rbac and app.ticketing] --> NOTIFY[NotificationService.notify]
    NOTIFY --> ROW[(notifications table — one row per recipient)]
    NOTIFY --> SSE[SSE push — sse_manager.py,\nskipped if no open connection]
    NOTIFY --> EMAILCHECK{Type in EMAIL_ELIGIBLE_\nNOTIFICATION_TYPES?}
    EMAILCHECK -->|yes| EMAILTASK[Fire-and-forget background task\n-> SMTP or logging-only]
    EMAILCHECK -->|no| SKIP[No email]
```

# Project Introduction

## What this is

UTMS (Unified Ticket Management System) is a combined **RBAC** (role-based access control: authentication, users, roles, permissions) and **support-ticketing** platform, served as one product from one FastAPI backend and one Next.js frontend.

It gives an organization:

- Role-based login and access control across six roles, with per-user and per-ticket permission overrides.
- A shared support-ticket workspace (Mail/Inbox, Tickets, SLA & escalation tracking, Reports) embedded directly into the same app users log into — not a separate product they're bounced to.
- Automated SLA and escalation tracking (First Response and Resolution clocks, breach notifications, auto-escalation through an ownership chain) running in-process, no external scheduler required.
- Real-time in-app notifications (Server-Sent Events) and outbound email for business-critical events.
- Optional Microsoft Graph mailbox integration for receiving/sending ticket-related email, with a mock provider for local development when Graph isn't configured.

## Why it exists

The system originated as two separate products — an RBAC/user-management service and a support-ticketing service — each with its own frontend, and was consolidated into one backend process and one frontend application (see [15-architecture-decisions](../15-architecture-decisions/README.md) for the reasoning). The consolidation was driven by a practical need: staff who work tickets shouldn't have to separately authenticate against, and mentally context-switch between, two different applications for what is functionally one job (handle a client's support request, end to end).

## What problem it solves

Client communication (primarily email) needs to be:
1. Reliably captured and associated with the right client and the right conversation thread.
2. Tracked against explicit time-based service commitments (SLA), with automatic visibility into risk before a breach happens.
3. Escalated through a real ownership chain when those commitments are at risk, without losing track of who is accountable.
4. Auditable — every significant state change (status, priority, assignment, escalation) recorded against a permanent trail.

All of the above while enforcing who can see and act on which tickets, based on role, category (department), and client ownership — with a mechanism for narrow, time-bound exceptions (permission overrides, ticket-scoped grants) rather than an all-or-nothing role system.

## Where to go next

- [business-objectives.md](business-objectives.md) for the business goals this system targets
- [users-and-roles.md](users-and-roles.md) for who uses it and what they can do
- [03-business-workflows](../03-business-workflows/README.md) to see the core email-to-resolution flow traced through the actual code

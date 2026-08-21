# Developer Onboarding

Goal: clone this repository and be running both services locally, understanding how to start development, without asking the original team basic setup questions.

1. [prerequisites.md](prerequisites.md) — what to install first
2. [repository-setup.md](repository-setup.md) — cloning and orienting yourself
3. [local-environment.md](local-environment.md) — the two-process local dev shape
4. [environment-variables.md](environment-variables.md) — constructing `.env`/`.env.local` (no template exists for the backend — this document is the template)
5. [database-setup.md](database-setup.md) — Neon, migrations, seeding
6. [backend-setup.md](backend-setup.md) — `unified-backend` step by step
7. [frontend-setup.md](frontend-setup.md) — `unified-frontend` step by step
8. [running-tests.md](running-tests.md) — and the one gotcha (three files that hang together)
9. [swagger.md](swagger.md) — using `/docs` to explore the API live
10. [first-feature-guide.md](first-feature-guide.md) — a suggested first change to make, and how to trace it through the layers
11. [development-guidelines.md](development-guidelines.md) — conventions this codebase actually follows

## The one-paragraph fast path

```bash
git clone <repo-url> && cd Unified-ticket-management-system
cd unified-backend && python -m venv .venv && .venv\Scripts\activate  # or source .venv/bin/activate
pip install -r requirements.txt
# construct .env — see environment-variables.md, no template exists
bash scripts/start.sh   # runs both Alembic chains, then uvicorn on :8000

# in a second terminal
cd unified-frontend && npm install
# create .env.local — see environment-variables.md
npm run dev   # :3000
```

Log in with the seeded Super Admin account (`admin@rbac.com` — check `unified-backend/scripts/rbac_seed/seed.py`'s `DEMO_USERS` for the current password, since credentials are seed-script content, not documentation content, and could change).

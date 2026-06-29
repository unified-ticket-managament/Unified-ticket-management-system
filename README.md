# Enterprise RBAC Platform

Production-grade Authentication, User Management & Role-Based Access Control (RBAC) platform.

## Architecture Overview

```
┌─────────────────┐     JWT + Refresh      ┌─────────────────┐
│   Next.js UI    │ ◄────────────────────► │   FastAPI API   │
│  (App Router)   │     Permission Guard   │  RBAC Middleware│
└────────┬────────┘                        └────────┬────────┘
         │                                          │
         │  React Query / Axios                     │ SQLAlchemy
         │  Zustand Auth Store                      │
         ▼                                          ▼
┌─────────────────┐                        ┌─────────────────┐
│ PermissionGuard │                        │   PostgreSQL    │
│ Dynamic UI ACL  │                        │  UUID + Indexes │
└─────────────────┘                        └─────────────────┘
```

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| Frontend | Next.js 14, TypeScript, TailwindCSS, TanStack Query, Axios, React Hook Form, Zod, Zustand, Shadcn UI, Framer Motion |
| Backend | FastAPI, SQLAlchemy, PostgreSQL, Alembic, JWT, Pydantic v2, Passlib/Bcrypt |
| DevOps | Docker, Docker Compose, Structured Logging |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Node.js 20+ (local frontend dev)
- Python 3.12+ (local backend dev)

### Run with Docker

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

**Default Super Admin credentials:**
- Email: `admin@rbac.local`
- Password: `Admin@123456`

### Local Development

**Backend:**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env
# Start PostgreSQL (or use docker compose up postgres)
python scripts/seed.py
uvicorn app.main:app --reload
```

**Frontend:**

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── api/v1/          # REST endpoints
│   │   ├── auth/            # Auth module
│   │   ├── core/            # Config, security, logging
│   │   ├── dependencies/    # DI & @require_permission
│   │   ├── middleware/      # Logging & security headers
│   │   ├── models/          # SQLAlchemy models
│   │   ├── repositories/    # Data access layer
│   │   ├── schemas/         # Pydantic v2 schemas
│   │   ├── services/        # Business logic
│   │   └── main.py
│   ├── alembic/             # Database migrations
│   └── scripts/seed.py      # Seed roles, permissions, admin
├── frontend/
│   └── src/
│       ├── app/             # Next.js App Router pages
│       ├── components/      # UI & layout components
│       ├── services/        # API client layer
│       ├── store/           # Zustand state
│       └── middleware.ts    # Route protection
├── docs/                    # Architecture & API docs
└── docker-compose.yml
```

## Database ER Diagram

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full ER diagram and design decisions.

## API Endpoints

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| POST | `/api/v1/auth/login` | Public | Login |
| POST | `/api/v1/auth/refresh` | Public | Refresh tokens |
| GET | `/api/v1/auth/me` | Authenticated | Current user + permissions |
| POST | `/api/v1/auth/logout` | Authenticated | Logout |
| PATCH | `/api/v1/auth/me` | Authenticated | Update profile |
| GET | `/api/v1/users` | `user:view` | List users |
| POST | `/api/v1/users` | `user:create` | Create user |
| PATCH | `/api/v1/users/{id}` | `user:update` | Update user |
| DELETE | `/api/v1/users/{id}` | `user:delete` | Soft delete user |
| GET | `/api/v1/roles` | `role:view` | List roles |
| POST | `/api/v1/roles` | `role:create` | Create role |
| PATCH | `/api/v1/roles/{id}` | `role:update` | Update role |
| DELETE | `/api/v1/roles/{id}` | `role:delete` | Delete role |
| GET | `/api/v1/permissions` | `permission:view` | List permissions |
| GET | `/api/v1/roles/{id}/permissions` | `permission:view` | Role permissions |
| PATCH | `/api/v1/roles/{id}/permissions` | `permission:update` | Update role permissions |
| GET | `/api/v1/audit-logs` | `audit:view` | Audit logs |

## Security Features

- Bcrypt password hashing
- JWT access tokens (30 min) + refresh tokens (7 days)
- Token rotation on refresh
- `@require_permission()` decorator on every protected endpoint
- Soft delete for users and roles
- Security headers middleware (XSS, clickjacking)
- Input validation via Pydantic v2 and Zod
- SQL injection prevention via SQLAlchemy ORM
- Automatic token refresh with logout on expiration

## Default Roles & Permissions

| Role | Access |
|------|--------|
| Super Admin | All permissions |
| Manager | user:view, user:create, user:update, role:view |
| Team Lead | user:view, user:update, role:view |
| Staff | user:view |
| Viewer | user:view, role:view, permission:view |

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for production deployment guide.

## License

MIT

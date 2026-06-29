# System Architecture

## High-Level Design

The platform follows **Clean Architecture** with clear separation of concerns:

```
Presentation Layer (API Routes)
        ↓
Service Layer (Business Logic + Audit)
        ↓
Repository Layer (Data Access)
        ↓
Database Layer (PostgreSQL)
```

## Entity Relationship Diagram

```mermaid
erDiagram
    USERS ||--o{ AUDIT_LOGS : performs
    USERS ||--o{ REFRESH_TOKENS : has
    USERS }o--|| ROLES : assigned_to
    ROLES ||--o{ ROLE_PERMISSIONS : has
    PERMISSIONS ||--o{ ROLE_PERMISSIONS : granted_via

    USERS {
        uuid id PK
        string name
        string email UK
        string password_hash
        uuid role_id FK
        boolean is_active
        timestamp created_at
        timestamp updated_at
        timestamp deleted_at
    }

    ROLES {
        uuid id PK
        string name UK
        text description
        timestamp created_at
        timestamp deleted_at
    }

    PERMISSIONS {
        uuid id PK
        string permission_name UK
        text description
    }

    ROLE_PERMISSIONS {
        uuid role_id PK,FK
        uuid permission_id PK,FK
    }

    AUDIT_LOGS {
        uuid id PK
        uuid user_id FK
        string action
        string entity_type
        string entity_id
        text old_value
        text new_value
        timestamp timestamp
    }

    REFRESH_TOKENS {
        uuid id PK
        uuid user_id FK
        string token_hash UK
        timestamp expires_at
        boolean revoked
        timestamp created_at
    }
```

## Authentication Flow

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant DB

    Client->>API: POST /auth/login (email, password)
    API->>DB: Verify credentials
    DB-->>API: User + Role + Permissions
    API->>API: Generate JWT + Refresh Token
    API->>DB: Store refresh token hash
    API-->>Client: access_token, refresh_token

    Client->>API: GET /users (Bearer token)
    API->>API: Decode JWT, load user permissions
    API->>API: Check require_permission("user:view")
    API->>DB: Query users
    API-->>Client: Paginated user list
```

## Authorization Engine

Permissions are **database-driven** and never hardcoded in the frontend logic:

1. On login, `/auth/me` returns the user's permission list
2. Frontend stores permissions in Zustand
3. `PermissionGuard` component conditionally renders UI
4. Backend `@require_permission()` enforces API access
5. Mismatch results in **403 Forbidden**

## Audit Logging

All critical actions are logged via `AuditService`:

| Action | Trigger |
|--------|---------|
| user.created | User creation |
| user.updated | User update |
| user.deleted | Soft delete |
| user.login | Successful login |
| user.logout | Logout |
| role.created | Role creation |
| role.updated | Role update |
| role.deleted | Role deletion |
| permission.updated | Role permission change |

## Frontend Architecture

```
src/
├── app/                    # Pages (App Router)
├── components/
│   ├── auth/               # PermissionGuard, AuthGuard
│   ├── layout/             # Dashboard shell, sidebar
│   └── ui/                 # Shadcn components
├── services/               # Axios API layer
├── store/                  # Zustand (auth + theme)
├── providers/              # React Query, theme
├── lib/                    # API client, utils
└── types/                  # TypeScript interfaces
```

## Scalability Considerations

- Stateless API servers (JWT-based auth)
- PostgreSQL with indexed foreign keys
- Repository pattern enables caching layer insertion
- Refresh token table supports token revocation
- Soft delete preserves audit trail integrity
- Modular permission system supports unlimited permissions

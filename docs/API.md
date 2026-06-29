# API Documentation

Base URL: `http://localhost:8000/api/v1`

Interactive docs: `http://localhost:8000/docs`

## Authentication

All protected endpoints require:

```
Authorization: Bearer <access_token>
```

### POST /auth/login

**Request:**
```json
{
  "email": "admin@rbac.local",
  "password": "Admin@123456"
}
```

**Response (200):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

### POST /auth/refresh

**Request:**
```json
{
  "refresh_token": "eyJ..."
}
```

**Response (200):** Same as login.

### GET /auth/me

**Response (200):**
```json
{
  "id": "uuid",
  "name": "Super Admin",
  "email": "admin@rbac.local",
  "role": "Super Admin",
  "role_id": "uuid",
  "permissions": ["user:create", "user:view", "..."],
  "is_active": true
}
```

### POST /auth/logout

**Request (optional):**
```json
{
  "refresh_token": "eyJ..."
}
```

### PATCH /auth/me

**Request:**
```json
{
  "name": "Updated Name",
  "email": "new@email.com",
  "current_password": "Admin@123456",
  "password": "NewPassword@123"
}
```

## Users

### GET /users

**Query Parameters:** `page`, `page_size`, `search`, `role_id`, `is_active`

**Permission:** `user:view`

**Response (200):**
```json
{
  "items": [...],
  "total": 25,
  "page": 1,
  "page_size": 10,
  "total_pages": 3
}
```

### POST /users

**Permission:** `user:create`

**Request:**
```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "password": "SecurePass@123",
  "role_id": "uuid",
  "is_active": true
}
```

### PATCH /users/{id}

**Permission:** `user:update`

### DELETE /users/{id}

**Permission:** `user:delete`

Returns `204 No Content`. Performs soft delete.

## Roles

### GET /roles — Permission: `role:view`
### POST /roles — Permission: `role:create`
### PATCH /roles/{id} — Permission: `role:update`
### DELETE /roles/{id} — Permission: `role:delete`

## Permissions

### GET /permissions — Permission: `permission:view`

### GET /roles/{id}/permissions — Permission: `permission:view`

### PATCH /roles/{id}/permissions — Permission: `permission:update`

**Request:**
```json
{
  "permission_ids": ["uuid1", "uuid2"]
}
```

## Audit Logs

### GET /audit-logs

**Permission:** `audit:view`

**Query Parameters:** `page`, `page_size`, `search`, `action`, `entity_type`, `user_id`

## Error Responses

| Status | Description |
|--------|-------------|
| 401 | Not authenticated / invalid token |
| 403 | Missing required permission |
| 404 | Resource not found |
| 409 | Conflict (duplicate email/role) |
| 422 | Validation error |

**Error format:**
```json
{
  "detail": "Missing required permission: user:create"
}
```

## JWT Payload

```json
{
  "sub": "user-uuid",
  "userId": "user-uuid",
  "email": "admin@rbac.local",
  "role": "Super Admin",
  "type": "access",
  "exp": 1719000000
}
```

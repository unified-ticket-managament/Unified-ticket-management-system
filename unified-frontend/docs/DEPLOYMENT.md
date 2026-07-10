# Deployment Guide

## Production Checklist

- [ ] Change `JWT_SECRET_KEY` to a cryptographically secure random string (64+ chars)
- [ ] Set `DEBUG=false`
- [ ] Configure production `DATABASE_URL`
- [ ] Set `CORS_ORIGINS` to your frontend domain only
- [ ] Enable HTTPS (TLS termination at load balancer or reverse proxy)
- [ ] Set `SECURE_COOKIES=true` if using cookie-based token storage
- [ ] Use managed PostgreSQL (RDS, Cloud SQL, Azure Database)
- [ ] Configure backup strategy for PostgreSQL
- [ ] Set up monitoring and alerting on `/health`

## Docker Production

1. Create production `.env` files for backend and frontend
2. Update `docker-compose.yml` for production (remove `--reload`, use secrets)
3. Deploy:

```bash
docker compose -f docker-compose.yml up -d --build
```

## Environment Variables

### Backend

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection | `postgresql+asyncpg://user:pass@host:5432/db` |
| `JWT_SECRET_KEY` | JWT signing key | Random 64-char string |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL | `7` |
| `CORS_ORIGINS` | Allowed origins | `https://app.example.com` |
| `LOG_LEVEL` | Log verbosity | `INFO` |

### Frontend

| Variable | Description | Example |
|----------|-------------|---------|
| `NEXT_PUBLIC_API_URL` | Backend API URL | `https://api.example.com/api/v1` |

## Database Migrations

```bash
cd backend
alembic upgrade head
python scripts/seed.py
```

## Reverse Proxy (Nginx Example)

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    location / {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

server {
    listen 443 ssl;
    server_name app.example.com;

    location / {
        proxy_pass http://frontend:3000;
        proxy_set_header Host $host;
    }
}
```

## Scaling

- **API**: Horizontal scaling behind load balancer (stateless JWT)
- **Database**: Read replicas for audit log queries
- **Frontend**: Static/SSR deployment on Vercel or container replicas

## Security Hardening

1. Rate limit `/auth/login` at reverse proxy level
2. Enable PostgreSQL SSL connections
3. Rotate JWT secret periodically (requires re-login)
4. Review audit logs regularly via `/audit-logs`
5. Disable default admin account after creating production admin

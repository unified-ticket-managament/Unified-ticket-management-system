# Enterprise RBAC Platform

A Role-Based Access Control (RBAC) system built using **FastAPI**, **Next.js**, **PostgreSQL**, **SQLAlchemy**, and **Alembic**.
The project uses a **shared-models** package to share the `User` and `Role` models across multiple services.

---

## Tech Stack

### Backend

* FastAPI
* SQLAlchemy
* PostgreSQL (Neon)
* Alembic
* Pydantic v2

### Frontend

* Next.js
* TypeScript
* Tailwind CSS

---

## Project Structure

```text
backend/
├── alembic/
├── app/
├── requirements.txt
└── .env

frontend/
├── app/
├── components/
├── services/
└── package.json
```

---

## Backend Setup

### 1. Navigate to backend

```bash
cd backend
```

### 2. Create Virtual Environment

**Windows**

```bash
python -m venv .venv
```

### 3. Activate Virtual Environment

**Windows**

```bash
.venv\Scripts\activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables

Create a `.env` file inside the backend folder.

Example:

```env
DATABASE_URL=your_neon_database_url
JWT_SECRET_KEY=your_secret_key
```

### 6. Run Database Migrations

```bash
alembic upgrade head
```

### 7. Start Backend Server

```bash
uvicorn app.main:app --reload
```
Backend runs at:

```
http://127.0.0.1:8000
```

API Documentation:

```
http://127.0.0.1:8000/docs
```

---

## Frontend Setup
### 1. Navigate to frontend

```bash
cd frontend
```

### 2. Install Dependencies

```bash
npm install
```

### 3. Configure Environment

Create a `.env.local` file.

Example:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 4. Start Frontend

```bash
npm run dev
```

Frontend runs at:

```
http://localhost:3000
```

---

## Database

Database: **PostgreSQL (Neon)**

ORM: **SQLAlchemy**

Migration Tool: **Alembic**

Shared Models:

* User
* Role

RBAC Models:

* Permission
* RolePermission
* AuditLog

---

## API Documentation

After starting the backend, visit:

```
http://127.0.0.1:8000/docs
```

---

## License

MIT License

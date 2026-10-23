# Local Development Guide (LMS Console & API)

This guide provides clear, step-by-step instructions to run and develop the Learning Management System (LMS) on your local machine.

---

## Architecture Overview

```
Browser (http://localhost:3000)
       │
       ▼
Next.js 16 Frontend (Port 3000)
       │  (BFF Proxy: /api/backend/*)
       ▼
FastAPI Backend (Port 8000)
       │
       ├─► PostgreSQL 16 (Port 5432 or 5433)
       └─► Redis 7 (Port 6379 or 6380)
```

- **Frontend**: Next.js 16 (App Router + Turbopack) running on `http://localhost:3000`.
- **Backend**: FastAPI (Python 3.12+ / 3.13) running on `http://localhost:8000`.
- **Database**: PostgreSQL 16 with `pgvector` extension.
- **Cache / Realtime**: Redis 7.

---

## Method 1: Running Directly from VS Code Terminals (Recommended for Fast Development)

This method provides hot-reloading for both the Python backend and Next.js frontend with maximum performance.

### Prerequisites
1. **Python 3.12+** (managed via `uv` or standard venv).
2. **Node.js 20+** and `npm`.
3. **PostgreSQL** running on `localhost:5432` (or via Docker container).
4. **Redis** running on `localhost:6379` (or via Docker container).

> [!TIP]
> If you don't have local Postgres and Redis installed on Windows, you can start just the database and cache with Docker:
> ```bash
> docker run -d --name lms-dev-postgres -p 5432:5432 -e POSTGRES_DB=lms_db -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=SHOHEL951753 pgvector/pgvector:pg16
> docker run -d --name lms-dev-redis -p 6379:6379 redis:7-alpine
> ```

---

### Step 1: Open Terminal 1 — Start the Backend

1. In VS Code, open a new terminal:
   ```powershell
   # 1. Run database migrations to make sure schema is up to date
   uv run alembic upgrade head

   # 2. Start the FastAPI backend server
   uv run python -m backend.main
   ```
2. You will see:
   ```text
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   ```
3. Test backend health in your browser or curl:
   - `http://localhost:8000/api/v1/auth/me` (returns 401 Unauthorized, meaning the API is alive and active).

---

### Step 2: Open Terminal 2 — Start the Frontend

1. In VS Code, open a second terminal:
   ```powershell
   # 1. Navigate to the frontend directory
   cd frontend

   # 2. (First time only) Install npm dependencies
   npm install

   # 3. Start the Next.js development server
   npm run dev
   ```
2. You will see:
   ```text
   ▲ Next.js 16 (Turbopack)
   - Local: http://localhost:3000
   ✓ Ready in ...
   ```
3. Open your browser and navigate to:
   - **`http://localhost:3000`** (or `http://localhost:3000/login`).

---

## Method 2: Running with Docker (One-Command Full Stack)

If you prefer to run everything inside isolated Docker containers without installing Python or local PostgreSQL:

### Start the Entire Stack
From the project root directory (`D:\LAIT\LMS_ANGIGRAVITY`):

```powershell
docker compose -f docker-compose.local.yml up --build
```

This single command builds and starts:
- `lms-local-postgres` on port `5433`
- `lms-local-redis` on port `6380`
- `lms-local-backend` on port `8000`
- `lms-local-webhooks-worker` (background worker)
- `lms-local-frontend` on port `3000`

### Run Database Migrations in Docker (First time or after schema changes)
Open a new terminal while Docker is running:
```powershell
docker compose -f docker-compose.local.yml run --rm backend alembic upgrade head
```

### Stop the Docker Stack
```powershell
docker compose -f docker-compose.local.yml down
```

---

## Troubleshooting Common Development Issues

### Issue 1: `GET http://localhost:3000/api/backend/auth/me 404 (Not Found)`
* **Root Cause**: Next.js App Router cached previous build artifacts inside `frontend/.next`, causing the dynamic BFF proxy route (`/api/backend/[...path]`) to fail to register.
* **Fix**:
  1. Stop the frontend server (`Ctrl + C` in the frontend terminal).
  2. Delete the `.next` cache directory:
     ```powershell
     # In PowerShell:
     Remove-Item -Recurse -Force frontend/.next
     ```
  3. Restart the dev server:
     ```powershell
     npm --prefix frontend run dev
     ```

### Issue 2: `The sign-in service could not be reached (502 / 504)`
* **Root Cause**: The Next.js frontend cannot connect to the Python backend on port 8000.
* **Fix**:
  1. Ensure the backend is running in Terminal 1 (`uv run python -m backend.main`).
  2. Verify `frontend/.env.local` contains:
     ```env
     LMS_API_URL=http://127.0.0.1:8000/api/v1
     ```

### Issue 3: Port 3000 or 8000 is already in use
* **Root Cause**: An orphaned Node or Python process from a previous session is still holding the port.
* **Fix**:
  ```powershell
  # Find and terminate processes on port 3000 or 8000:
  Get-Process -Id (Get-NetTCPConnection -LocalPort 3000, 8000 -ErrorAction SilentlyContinue).OwningProcess | Stop-Process -Force
  ```


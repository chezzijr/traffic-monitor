# How to Run

Two ways to run the stack: **shell scripts** (local dev, each service in its own terminal) or **Docker Compose** (everything in one command).

---

## Option 1 — Shell Scripts (Local Dev)

Each script runs one service. Open a separate terminal for each.

### Prerequisites

- [uv](https://docs.astral.sh/uv/) installed
- [Bun](https://bun.sh/) installed
- [SUMO](https://sumo.dlr.de/docs/Installing/index.html) installed with `SUMO_HOME` set
- [Docker](https://docs.docker.com/get-docker/) installed (needed for Redis)
- [Redis](https://redis.io/) — started automatically by `run-backend.sh`

### Step 1 — Backend + Redis

```bash
bash sh/run-backend.sh
```

Starts a Redis container (`dev-redis` on port 6379) then launches the FastAPI backend on port 8000. Press `Ctrl+C` to stop both.

### Step 2 — Celery Worker

```bash
bash sh/run-celery.sh
```

Starts the Celery worker (connects to the Redis started in Step 1). Required for training jobs.

### Step 3 — Digital Twin Service

```bash
bash sh/run-digital-twin.sh
```

Starts the Digital Twin video-analysis + SUMO deploy service on port 8001.

### Step 4 — Frontend

```bash
bash sh/run-frontend.sh
```

Starts the Vite dev server on port 5173.

### Step 5 — Camera Collector (optional)

```bash
bash sh/run-service.sh
```

Starts the camera collector service. Only needed if you have live camera feeds configured.

### Service URLs

| Service         | URL                        |
|-----------------|----------------------------|
| Frontend        | http://localhost:5173       |
| Backend API     | http://localhost:8000       |
| Digital Twin    | http://localhost:8001       |
| Redis           | localhost:6379              |

---

## Option 2 — Docker Compose

Builds and runs all services in containers with a single command.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose v2
- NVIDIA GPU + drivers (for YOLO inference and Celery GPU tasks)

### Run (with GPU)

```bash
docker compose up --build
```

### Run (without NVIDIA GPU)

Remove the GPU reservations by passing the no-gpu override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.no-gpu.yml up --build
```

### Run in background

```bash
docker compose up --build -d
docker compose logs -f          # stream logs from all services
docker compose logs frontend -f # stream logs from one service
```

### Stop

```bash
docker compose down
```

### Rebuild a single service after code changes

```bash
docker compose up --build backend celery-worker -d
```

### Service URLs (Docker)

| Service         | URL                        |
|-----------------|----------------------------|
| Frontend        | http://localhost:5173       |
| Backend API     | http://localhost:8000       |
| Digital Twin    | http://localhost:8001       |
| Redis           | localhost:6379              |

### Production build

```bash
docker compose -f docker-compose.prod.yml up --build
```

Serves the frontend via Nginx on port 80 instead of the Vite dev server.

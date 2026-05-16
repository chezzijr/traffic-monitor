# How to Run

Two ways to run the stack: **local dev** (each service in its own terminal) or **Docker Compose** (all-in-one).

---

## Option 1 — Local Dev

### Prerequisites

Install these tools before anything else:

| Tool | Version | Install |
|------|---------|---------|
| Python | ≥ 3.11 | https://www.python.org/downloads/ |
| [uv](https://docs.astral.sh/uv/) | latest | `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [Bun](https://bun.sh/) | latest | `curl -fsSL https://bun.sh/install \| bash` |
| [SUMO](https://sumo.dlr.de/docs/Installing/index.html) | ≥ 1.18 | Download installer, then set `SUMO_HOME` env var |
| [Docker](https://docs.docker.com/get-docker/) | latest | Needed to run Redis |
| Git LFS | latest | https://git-lfs.com/ — run `git lfs install` then `git lfs pull` after cloning |

---

### Step 1 — Install Backend Dependencies

```bash
cd backend
uv sync
cd ..
```

---

### Step 2 — Install Digital Twin Dependencies

```bash
cd services/digital_twin
uv sync
cd ../..
```

> **No GPU?** Open `services/digital_twin/pyproject.toml`, delete the `[[tool.uv.index]]` block, then rerun `uv sync` to get CPU-only PyTorch.

---

### Step 3 — Install Camera Collector Dependencies (optional)

Only needed if you want live camera data collection.

```bash
cd services/camera_collector
uv sync
cd ../..
```

---

### Step 4 — Install Frontend Dependencies

```bash
cd frontend
bun install
cd ..
```

---

### Step 5 — Run All Services

Open **four terminals** from the repo root and run one command per terminal in order.

**Terminal 1 — Redis**

```bash
docker run -d --rm --name dev-redis -p 6379:6379 redis:alpine
```

**Terminal 2 — Backend API** (port 8000)

```bash
cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 3 — Celery Worker**

```bash
cd backend && uv run celery -A app.celery_app worker --loglevel=info --pool=solo
```

**Terminal 4 — Digital Twin Service** (port 8001)

```bash
cd services/digital_twin && uv run uvicorn service.main:app --host 0.0.0.0 --port 8001
```

**Terminal 5 — Frontend** (port 5173)

```bash
cd frontend && bun dev
```

**Terminal 6 — Camera Collector** (optional)

```bash
cd services/camera_collector && uv run python -m service.main
```

---

### Service URLs

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Backend API docs | http://localhost:8000/docs |
| Digital Twin | http://localhost:8001 |

---

## Option 2 — Docker Compose

No local Python/Bun setup needed.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose v2
- `git lfs pull` after cloning to fetch model/video files
- NVIDIA GPU + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) (for GPU acceleration)

---

### Run — with NVIDIA GPU

```bash
docker compose up --build
```

### Run — without NVIDIA GPU

```bash
docker compose -f docker-compose.yml -f docker-compose.no-gpu.yml up --build
```

### Run in the background

```bash
docker compose up --build -d
```

### View logs

```bash
docker compose logs -f                  # all services
docker compose logs -f backend          # backend only
docker compose logs -f digital-twin     # digital twin only
docker compose logs -f celery-worker    # celery only
```

### Stop

```bash
docker compose down
```

### Rebuild after code changes

```bash
docker compose up --build backend celery-worker -d
```

### Service URLs (Docker)

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Backend API docs | http://localhost:8000/docs |
| Digital Twin | http://localhost:8001 |

### Production build

```bash
docker compose -f docker-compose.prod.yml up --build
```

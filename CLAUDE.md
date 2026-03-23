# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Traffic Light Optimization Web App - a full-stack application for real-time traffic monitoring and reinforcement learning-based traffic light optimization. Uses SUMO (Simulation of Urban Mobility), OpenStreetMap data extraction, and RL algorithms (DQN, PPO) to optimize traffic flow at single or multiple intersections simultaneously.

## Commands

### Backend (Python/uv)

```bash
cd backend
uv sync                                    # Install dependencies
uv run uvicorn app.main:app --reload --port 8000  # Start dev server
uv run celery -A app.celery_app worker --loglevel=info --concurrency=1  # Start Celery worker (1 = SUMO is heavy)
uv run pytest                              # Run all tests
uv run pytest tests/test_api_health.py -v  # Run specific test file
```

### Frontend (Bun)

```bash
cd frontend
bun install            # Install dependencies
bun dev                # Start dev server on :5173
bun run build          # Production build (TypeScript + Vite)
bun lint               # ESLint check
```

### Docker

```bash
# Dev: frontend:5173, backend:8000, redis:6379, celery-worker
docker-compose up --build
# Prod: nginx:80, backend:8000, redis:6379
docker-compose -f docker-compose.prod.yml up --build
```

Dev stack has 4 services: frontend, backend, redis, celery-worker. The `simulation/` volume is shared between backend and celery-worker.

## Architecture

**Distributed system with async task queue. Map-first UX: select region → extract network → select junctions → train RL models → deploy.**

1. **Frontend (React 19 + TypeScript + Vite)**: Leaflet map for region selection and junction picking, Recharts for training metrics visualization, Zustand stores (`mapStore`, `trainingStore`, `modelStore`). Component groups: Map/, Control/, Training/, Models/, Dashboard/, Layout/. `TrainingSSE` service for real-time progress streaming via SSE.

2. **Backend (FastAPI)**: Seven route modules:
   - `routes/map.py` - OSM extraction, SUMO conversion, network caching
   - `routes/metrics.py` - Vehicle counts, wait times, throughput
   - `routes/control.py` - Traffic light phase control
   - `routes/traffic_light.py` - Traffic light state queries
   - `routes/training.py` - ML training dispatch (single/multi-junction) and SSE streaming
   - `routes/tasks.py` - Celery task management, cancellation, and SSE progress streaming
   - `routes/networks.py` - Persisted network metadata CRUD

3. **Services:**
   - `osm_service.py` - OSM data fetching with hash-based disk caching
   - `sumo_service.py` - Thread-safe TraCI wrapper with global SimulationState
   - `ml_service.py` - Model management (list, load, predict, delete); no thread-based training
   - `metrics_service.py` - In-memory metrics collection
   - `task_service.py` - Celery task creation/query/cancellation, Redis progress caching, SSE streaming
   - `network_service.py` - Network metadata persistence (.meta.json alongside .net.xml)
   - `deployment_service.py` - Track deployed ML models on traffic lights
   - `validation_service.py` - Business rule validation for training/deployment requests
   - `route_service.py` - Vehicle route generation using SUMO tools (randomTrips.py, duarouter)
   - `traffic_light_service.py` - Traffic light state queries via TraCI

4. **ML Pipeline (`ml/`) — LibSignal V1 approach:**
   - *Single-agent:* `environment.py` (V1 Gymnasium env, LibSignal-style yellow phase creation, direct TraCI), `trainer.py` (custom DQN/PPO training loops, no SB3)
   - *Multi-agent:* `multi_agent_env_v2.py` (N junctions sharing one SUMO instance), `multi_agent_trainer.py` (custom collect-train loop, max 10 junctions, still uses SB3)
   - *Networks:* `networks/dqn_network.py` (`DQNAgent` with replay buffer, epsilon-greedy, [in→20→20→actions]), `networks/ppo_network.py` (`PPOAgent` Actor-Critic [in→64→64])
   - *Rewards:* `rewards.py` — all algorithms: `-mean(halting) * 12.0` (LibSignal unified reward)
   - *Observation:* `[lane_vehicle_counts, phase_one_hot]` (dimension: num_lanes + num_green_phases)
   - *Yellow phases:* Dynamically created pairwise yellow transitions between all green phases (LibSignal `create_yellows` pattern), installed as custom SUMO program `{tl_id}_rl`
   - *DQN hyperparams:* lr=1e-3 (RMSprop), buffer=5000 (deque), batch=64, gamma=0.95, epsilon=0.1→0.01 (multiplicative 0.995), hard target copy every 10 decisions, grad_clip=5.0, learning_start=1000
   - *PPO hyperparams:* lr=3e-4 (Adam), n_steps=360, n_epochs=4, gamma=0.99, clip=0.1, GAE lambda=0.95
   - *Model format:* `.pt` (PyTorch state dict), legacy `.zip` (SB3) still loadable

5. **Task Queue (Celery + Redis):** Long-running training dispatched to Celery workers (concurrency=1 per worker, SUMO is heavy). Tasks publish progress via Redis Pub/Sub (every 500 steps); backend streams to frontend via SSE. Tasks: `train_traffic_light` (single-agent), `train_multi_junction` (multi-agent). GPU support via `torch.cuda.is_available()`.

## `simulation/` Directory

Runtime data directory (shared volume in Docker):

```
simulation/
├── networks/    # .net.xml, .rou.xml, .meta.json per network hash
├── models/      # Trained RL models: {network}_{junction}_{algo}_{timestamp}.pt (or .zip for legacy)
└── vtypes/      # Vehicle type definitions (vietnamese_vtypes.add.xml)
```

## Key Patterns

- **Map-first training flow**: Region selection → OSM extract → SUMO convert → junction selection → training config → Celery dispatch → SSE progress → model deploy
- **Thread-safe simulation state**: `sumo_service.py` uses mutex lock for concurrent access
- **Lazy SUMO loading**: Graceful fallback if SUMO not installed; runtime checks
- **Pydantic schemas**: All request/response models in `models/schemas.py`
- **Celery task dispatch**: Routes enqueue tasks → Celery workers execute → Redis Pub/Sub progress → SSE to frontend
- **Network metadata persistence**: `.meta.json` files stored alongside `.net.xml` in `simulation/networks/`
- **Zustand selector pattern**: All components use fine-grained selectors `useStore((s) => s.field)` to minimize re-renders
- **Direct TraCI in training**: Training environments use TraCI directly (not sumo_service) — each training task owns its own SUMO instance

## Environment Variables

**Backend** (.env):
- `SUMO_HOME` - SUMO installation path (default: `/usr/share/sumo`)
- `CORS_ORIGINS` - Allowed CORS origins (default: `["http://localhost:5173"]`)
- `CELERY_BROKER_URL` - Redis broker URL (default: `redis://localhost:6379/0`)
- `CELERY_RESULT_BACKEND` - Redis result backend (default: `redis://localhost:6379/0`)
- `REDIS_HOST` - Redis host for pub/sub (default: `localhost`)
- `REDIS_PORT` - Redis port (default: `6379`)

**Frontend**:
- `VITE_API_URL` - Backend API URL (default: `http://localhost:8000`)

## CLI Testing Pipeline (no frontend needed)

All testing can be done via `curl` against the running Docker stack (`docker compose up --build`).

### Test network: `b14e4a2c9df9be98`

Pre-extracted network (Ho Chi Minh City area, bbox: 10.7758-10.7860 N, 106.6819-106.6966 E). Has 34 traffic lights. If this network doesn't exist, extract it:

```bash
# Extract region from OSM (only needed once)
curl -s -X POST http://localhost:8000/api/map/extract-region \
  -H "Content-Type: application/json" \
  -d '{"south": 10.775828, "west": 106.681924, "north": 10.785967, "east": 106.696558}' | jq .

# Convert to SUMO network (use the network_id from above)
curl -s -X POST http://localhost:8000/api/map/convert-to-sumo/b14e4a2c9df9be98 | jq .
```

### List available networks and TL IDs

```bash
curl -s http://localhost:8000/api/networks/ | jq '.[0] | {network_id, traffic_light_count, junctions: [.junctions[:5][] | .tl_id]}'
```

### Single-junction DQN training (quick test)

```bash
# Start training (5000 timesteps ≈ 13 episodes, ~2 min)
curl -s -X POST http://localhost:8000/api/training/single \
  -H "Content-Type: application/json" \
  -d '{
    "network_id": "b14e4a2c9df9be98",
    "tl_id": "411918637",
    "algorithm": "dqn",
    "total_timesteps": 5000,
    "scenario": "moderate"
  }' | jq .
# Returns: {"task_id": "...", "status": "queued"}

# Monitor progress via task status
curl -s http://localhost:8000/api/tasks/<TASK_ID>/status | jq .

# Or stream SSE progress (ctrl+C to stop)
curl -N http://localhost:8000/api/tasks/<TASK_ID>/stream

# Watch celery worker logs for episode rewards
docker compose logs celery-worker -f --tail 5
```

Expected reward progression: starts around -28 to -32, improves to -3 to -1 by episode 13.

### Single-junction PPO training

```bash
curl -s -X POST http://localhost:8000/api/training/single \
  -H "Content-Type: application/json" \
  -d '{
    "network_id": "b14e4a2c9df9be98",
    "tl_id": "411918637",
    "algorithm": "ppo",
    "total_timesteps": 5000,
    "scenario": "moderate"
  }' | jq .
```

### Multi-junction training

```bash
curl -s -X POST http://localhost:8000/api/training/multi \
  -H "Content-Type: application/json" \
  -d '{
    "network_id": "b14e4a2c9df9be98",
    "tl_ids": ["411918637", "411918820"],
    "algorithm": "dqn",
    "total_timesteps": 10000,
    "scenario": "moderate"
  }' | jq .
```

Note: multi-junction still uses V2 env (SUMO-RL style) and SB3 internally.

### List trained models

```bash
curl -s http://localhost:8000/api/models/ | jq '.[0] | {model_id, algorithm, type, path}'
```

### Task management

```bash
# List all tasks
curl -s http://localhost:8000/api/tasks/ | jq .

# Cancel a running task
curl -s -X POST http://localhost:8000/api/tasks/<TASK_ID>/cancel | jq .
```

### Scenarios

`scenario` values: `light` (0.3 veh/s), `moderate` (0.8 veh/s), `heavy` (1.5 veh/s), `rush_hour` (2.0 veh/s).

### Useful TL IDs for network `b14e4a2c9df9be98`

- `411918637` — simple 2-phase intersection, good for quick tests
- `411918820`, `411918854` — additional test junctions
- `cluster_13625475216_13625475217_411917834` — cluster junction (more phases)

### Rebuilding after code changes

```bash
docker compose up --build backend celery-worker -d   # Rebuild backend + worker
docker compose logs celery-worker -f --tail 5         # Watch worker logs
```

## Prerequisites

- Python 3.13+
- SUMO with `SUMO_HOME` set
- Redis for Celery broker and pub/sub

# Traffic Light Optimization Web App

A web application for real-time traffic monitoring and traffic light optimization using SUMO (Simulation of Urban Mobility) and reinforcement learning.

## Features

- **Map Integration**: Extract road networks from OpenStreetMap for any geographic region
- **Traffic Simulation**: Run SUMO simulations with real-time vehicle tracking
- **Metrics Collection**: Track vehicle counts, wait times, and throughput
- **Traffic Light Control**: Manual and automated control of traffic light phases
- **ML-Powered Optimization**: Reinforcement learning agent (Stable-Baselines3) for traffic light timing optimization
- **Interactive Frontend**: React-based dashboard with live simulation visualization

## Architecture

```
traffic-monitor/
├── backend/          # FastAPI backend
│   ├── app/
│   │   ├── api/      # REST API routes
│   │   ├── ml/       # ML agent and training
│   │   ├── models/   # Pydantic schemas
│   │   └── services/ # Business logic
│   └── tests/        # pytest tests
├── frontend/         # React + TypeScript + Vite
└── simulation/       # SUMO network files
```

## Prerequisites

- **Python** 3.11 or higher
- **Node.js** 18+ or **Bun** (recommended)
- **SUMO** (Simulation of Urban Mobility) installed with `SUMO_HOME` environment variable set
- **Redis** for Celery task queue
- **Docker** and **Docker Compose** (optional, for containerized deployment)

### Installing SUMO

**Arch Linux:**
```bash
sudo pacman -S sumo
```

**Ubuntu/Debian:**
```bash
sudo add-apt-repository ppa:sumo/stable
sudo apt-get update
sudo apt-get install sumo sumo-tools sumo-doc
```

**macOS:**
```bash
brew install sumo
```

Set the environment variable:
```bash
export SUMO_HOME=/usr/share/sumo  # or your SUMO installation path
```

## Quick Start (Development)

### Backend

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Install dependencies using uv:
   ```bash
   uv sync
   ```

3. Start Redis (required for task queue):
   ```bash
   docker run -d -p 6379:6379 redis:alpine
   # or if Redis is installed locally:
   redis-server
   ```

4. Run the backend server:
   ```bash
   uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   The API will be available at `http://localhost:8000`

### Frontend

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   bun install
   # or: pnpm install / npm install
   ```

3. Start the development server:
   ```bash
   bun dev
   # or: pnpm dev / npm run dev
   ```

   The frontend will be available at `http://localhost:5173`

### Running Tests

Backend tests:
```bash
cd backend
uv run pytest
```

Run specific test files:
```bash
uv run pytest tests/test_api_health.py -v
```

## Docker Deployment

### Development

```bash
docker-compose up --build
```

This starts:
- Frontend at `http://localhost:5173`
- Backend at `http://localhost:8000`
- Redis at `localhost:6379`

### Production

```bash
docker-compose -f docker-compose.prod.yml up --build -d
```

This starts:
- Frontend (via nginx) at `http://localhost:80`
- Backend at `http://localhost:8000`
- Redis at `localhost:6379`

## API Documentation

When the backend is running, interactive API documentation is available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| **Map** |||
| `POST` | `/api/map/extract-region` | Extract OSM road network |
| `GET` | `/api/map/intersections/{network_id}` | Get intersections |
| `POST` | `/api/map/convert-to-sumo/{network_id}` | Convert to SUMO format |
| `GET` | `/api/map/networks` | List cached networks |
| **Simulation** |||
| `POST` | `/api/simulation/start` | Start simulation |
| `POST` | `/api/simulation/step` | Advance one step |
| `POST` | `/api/simulation/pause` | Pause simulation |
| `POST` | `/api/simulation/resume` | Resume simulation |
| `POST` | `/api/simulation/stop` | Stop simulation |
| `GET` | `/api/simulation/status` | Get current status |
| **Metrics** |||
| `GET` | `/api/metrics/current` | Get current metrics |
| `GET` | `/api/metrics/history` | Get metrics history |
| `GET` | `/api/metrics/summary` | Get summary statistics |
| `DELETE` | `/api/metrics/clear` | Clear metrics |
| **Control** |||
| `GET` | `/api/control/traffic-lights` | List traffic lights |
| `GET` | `/api/control/traffic-lights/{id}` | Get traffic light |
| `POST` | `/api/control/traffic-lights/{id}/phase` | Set traffic light phase |

## Configuration

### Backend Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMO_HOME` | `/usr/share/sumo` | SUMO installation path |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins |

### Frontend Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `http://localhost:8000` | Backend API URL |

## Development

### Code Style

- Backend: Follow PEP 8, use type hints
- Frontend: ESLint configuration included

### Adding Tests

Tests are located in `backend/tests/`. Add new test files with the `test_` prefix:

```python
# backend/tests/test_my_feature.py
def test_my_feature(client):
    response = client.get("/api/my-endpoint")
    assert response.status_code == 200
```

## License

This project is for educational and research purposes.

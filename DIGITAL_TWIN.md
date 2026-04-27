# 🏙️ Digital Twin Service Context

This document provides essential context for the `digital_twin` service within the Traffic Light Optimization project. This service serves as a mock for real-time surveillance camera feeds in Ho Chi Minh City.

---

## 🎯 Role & Objective
The **Digital Twin** service is responsible for simulating real-world traffic camera feeds by processing pre-recorded video data. It performs real-time vehicle detection and tracking to estimate traffic states (queue counts) and infer traffic light phases.

**Your primary job:** Maintain, optimize, and extend the `digital_twin` service located in `services/digital_twin`.

---

## 🏛️ Architecture Overview
The service is a standalone FastAPI microservice that runs a continuous background processing loop.

- **Background Loop**: Loads a YOLO model and a pre-recorded video. It "streams" the video, tracking vehicles and counting those that are "waiting" (speed below a threshold) in specific regions (North, South, East, West).
- **Atomic Snapshot**: The processor maintains a single in-memory snapshot containing the latest original frame, annotated frame (with BBs), and direction counts.
- **REST API**: Exposes the cached snapshot data instantly to the main backend/frontend.

---

## 🛠️ Tech Stack
| Component | Technology |
|-----------|------------|
| **Framework** | FastAPI (Python 3.11+) |
| **ML Model** | YOLOv11 (Ultralytics) |
| **Processing** | OpenCV (cv2) |
| **Concurrency** | Threading (Background Loop + Atomic Locks) |
| **Data Format** | Pydantic (Schemas), Base64 (Images) |

---

## 📂 File Structure
```
services/digital_twin/
├── service/
│   ├── main.py            # FastAPI entry point & routes
│   ├── video_analyzer.py  # Core logic: YOLO tracking & snapshot management
│   ├── config.py          # Service configuration & constants
│   ├── region_helpers.py  # Geometry logic for N/S/E/W regions
│   └── __init__.py
├── data/
│   └── traffic_video/     # Pre-recorded HCMC videos & regions.json
├── model/
│   └── yolo11x.pt         # YOLO weights
├── pyproject.toml         # Dependencies managed by uv
└── Dockerfile              # Containerization
```

---

## 📡 API Endpoints (Port 8001)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/waiting_count` | `GET` | Returns list of waiting vehicles per direction. |
| `/frame` | `GET` | Returns latest original and annotated frames (Base64). |
| `/traffic_light_state` | `GET` | Returns inferred red/green states for all directions. |
| `/health` | `GET` | Service status check. |

---

## 🧠 Key Logic & Conventions

### 1. Vehicle Waiting Detection
A vehicle is marked as **"WAITING"** if:
- It is within a defined direction region (North, South, East, West).
- Its smoothed speed is below `WAITING_SPEED_THRESHOLD` (default: 2.0 m/s).
- Metric: `speed = (distance_px * METERS_PER_PIXEL) / (frame_diff / fps)`.

### 2. Traffic Light Inference
Since we don't have real-time API access to HCMC traffic lights, we infer them:
- **Rule**: If waiting vehicles in a direction axis (e.g., North) exceeds `WAITING_VEHICLE_RED_THRESHOLD`, that axis is considered **RED**.
- **Mutual Exclusion**: If North/South is RED, East/West is GREEN (and vice-versa).
- **Sticky States**: A state must hold for at least `MIN_LIGHT_DURATION_SECS` (default: 20s) to avoid rapid flickering.
- **Mirroring**: South mirrors North; West mirrors East.

### 3. Resource Optimization
- `YOLO_VID_STRIDE`: Processes every Nth frame (default: 3) to achieve near real-time performance on standard hardware.
- `half=True`: Can be used in `model.track` for GPU optimization (FP16).

---

## 🚀 Development Commands

### Start Service
```bash
cd services/digital_twin
uv sync
uv run python -m service.main
```

### Test API
```bash
# Get vehicle counts
curl http://localhost:8001/waiting_count?id_camera=tphcm-2p

# Get inferred lights
curl http://localhost:8001/traffic_light_state
```

---

## ⚠️ Known Constraints
- **Looping Video**: The video restarts automatically when it ends. Logic should handle the "jump" in tracking IDs gracefully.
- **Single Camera**: Currently optimized for one camera intersection at a time per service instance.
- **Perspective**: Region definitions are sensitive to the specific video angle provided in `regions.json`.

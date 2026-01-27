# 🚀 Traffic Light Optimization Web App - Bootstrap Plan Summary

---

## 🏛️ Two-System Architecture

This project implements two distinct but related systems:

### SYSTEM 1: Training Environment (Current MVP Focus)

Uses SUMO simulation for RL agent training:

```
Region Selection → OSM Extraction → Route Generation → SUMO Simulation
                                         ↓
                           Vietnamese Traffic Patterns
                           (80% motorbikes, 15% cars, 5% buses)
                                         ↓
                              RL Agent Training (DQN/PPO)
                                         ↓
                              Export Trained Model
```

**Key Components:**
- Interactive map for region selection
- OSM data extraction and SUMO network conversion
- Route generation with Vietnamese vehicle types
- Gymnasium environment wrapping SUMO
- Stable-Baselines3 for training

### SYSTEM 2: Real-Time Monitoring (Future Phase)

Uses camera feeds for real-world deployment:

```
Camera Input → Vehicle Detection (YOLO) → Traffic State Estimation
                                                    ↓
                                          Trained Model Inference
                                                    ↓
                                        Traffic Light Control
```

**Key Components (Future):**
- Camera feed integration (video/stream/mock)
- YOLOv8 vehicle detection
- Real-time state estimation
- Trained model inference
- Traffic light actuation

---

**Current Status:** System 1 is the MVP focus. System 2 is planned for future development after successful training results.

---

## 📋 MVP Scope (6 Weeks)

### Must Have (Phase 1)
- Interactive map centered on HCMC with OpenStreetMap
- Region selection tool (draw bounding box)
- OSM to SUMO network extraction
- Basic SUMO simulation control (start/stop/step)
- Single intersection RL environment (DQN or PPO)
- Metrics dashboard (waiting time, queue length, throughput)
- Manual traffic light control panel

### Nice to Have (Phase 2)
- Camera feed integration (placeholder/mock initially)
- Traffic heatmap overlay showing congestion
- Historical metrics storage and trends
- Model evaluation comparison (RL vs fixed-time baseline)

### Future/Out of Scope
- Multi-agent RL for multiple intersections
- Real-time deployment to physical traffic lights
- Transfer learning for region specialization

---

## 🛠️ Tech Stack Summary

| Layer | Technology |
|-------|------------|
| **Frontend** | React + TypeScript, React-Leaflet, Zustand, Tailwind CSS, Recharts |
| **Backend** | FastAPI (Python), PostgreSQL + TimescaleDB, Redis, Celery |
| **ML/Simulation** | SUMO, sumo-rl, Stable-Baselines3, OSMnx |
| **Detection** | YOLOv8 (optional, for camera feeds) |
| **DevOps** | Docker, Docker Compose |

---

## 🏗️ System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   FRONTEND (React)                       │
│   Map View | Dashboard | Control Panel | Camera View     │
└──────────────────────┬───────────────────────────────────┘
                       │ REST API / WebSocket
┌──────────────────────┴───────────────────────────────────┐
│                   BACKEND (FastAPI)                      │
│   Map API | Simulation API | Metrics API | Control API   │
└───────┬──────────────┬──────────────┬────────────────────┘
        │              │              │
   PostgreSQL       Redis         Celery
   (TimescaleDB)    (Cache)       (Background Tasks)
                                      │
┌─────────────────────────────────────┴────────────────────┐
│              ML / SIMULATION LAYER                       │
│      SUMO Simulator | sumo-rl Environment | RL Agent     │
└──────────────────────────────────────────────────────────┘
```

> **Note:** This architecture shows the current MVP (System 1 - Training).
> Camera integration (System 2 - Monitoring) will be added in future phases.

---

## 📅 Week-by-Week Execution

### **Week 1: Project Setup & Basic Map**
| Day | Task |
|-----|------|
| 1-2 | Initialize React + FastAPI projects, install dependencies |
| 3-4 | Implement MapContainer with React-Leaflet, HCMC center |
| 5 | Add region selection tool (draw rectangle on map) |

**Deliverable:** Map displaying HCMC with ability to select a region

---

### **Week 2: Backend API & OSM Integration**
| Day | Task |
|-----|------|
| 1-2 | Set up FastAPI structure, create route modules |
| 3-4 | Implement OSM service using OSMnx to extract road network |
| 5 | Create endpoint to convert selected region → SUMO network file |

**Deliverable:** API that extracts intersections from any selected HCMC region

---

### **Week 3: SUMO Integration & Simulation**
| Day | Task |
|-----|------|
| 1-2 | Implement SUMO service (start, stop, step simulation) |
| 3 | Create traffic light control endpoints via TraCI |
| 4-5 | Connect frontend to simulation API, display simulation status |

**Deliverable:** Working SUMO simulation controllable via web interface

---

### **Week 4: RL Environment & Training**
| Day | Task |
|-----|------|
| 1-2 | Create Gymnasium-compatible environment wrapping SUMO |
| 3 | Define state space (queue lengths, waiting times, current phase) |
| 4 | Define action space (phase selection) and reward (negative waiting time) |
| 5 | Implement training script with Stable-Baselines3 (DQN/PPO) |

**Deliverable:** Trainable RL agent for single intersection

---

### **Week 5: Dashboard & Full Integration**
| Day | Task |
|-----|------|
| 1-2 | Build metrics panel with real-time charts (Recharts) |
| 3 | Implement traffic light control UI component |
| 4 | Add placeholder camera panel and traffic heatmap layer |
| 5 | Connect all components, end-to-end testing |

**Deliverable:** Complete integrated dashboard with all features working

---

### **Week 6: Polish, Testing & Documentation**
| Day | Task |
|-----|------|
| 1-2 | Write unit tests and integration tests |
| 3 | Run baseline comparison (fixed-time vs RL-controlled) |
| 4 | Write documentation, README, API docs |
| 5 | Record demo video, prepare thesis figures/charts |

**Deliverable:** Production-ready MVP with documentation and results

---

## 📁 Project Structure Overview

```
traffic-optimization/
├── frontend/
│   └── src/
│       ├── components/      # Map, Dashboard, Control, Layout
│       ├── hooks/           # Custom React hooks
│       ├── services/        # API calls
│       ├── store/           # Zustand state management
│       └── types/           # TypeScript interfaces
├── backend/
│   └── app/
│       ├── api/routes/      # FastAPI endpoints
│       ├── services/        # OSM, SUMO, Metrics services
│       ├── models/          # Database & Pydantic schemas
│       └── ml/              # RL environment, agent, trainer
├── simulation/
│   ├── networks/            # Generated SUMO networks
│   ├── routes/              # Traffic demand files
│   └── configs/             # SUMO configuration
└── docker-compose.yml
```

---

## 📊 Key Metrics to Track

| Metric | Description | Purpose |
|--------|-------------|---------|
| Average Waiting Time | Mean time vehicles wait at red lights | Primary optimization target |
| Queue Length | Number of halted vehicles per lane | Congestion indicator |
| Throughput | Vehicles passing per hour | Efficiency measure |
| Total Delay | Extra travel time vs free-flow | Overall performance |

---

## ⚠️ Key Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **OSM data quality** | Poor network extraction for HCMC | Focus on well-mapped district (District 1 or 7) |
| **Sim-to-real gap** | RL model may not transfer to real world | Acknowledge as limitation, focus on simulation results |
| **SUMO complexity** | Learning curve for traffic simulation | Use sumo-rl library, start with simple 4-way intersection |
| **Training time** | RL training can be slow | Use simple network, limit training episodes |
| **Scope creep** | Too many features for thesis timeline | Strict MVP focus, defer nice-to-haves |

---

## 🎯 Thesis Deliverables Checklist

- [ ] Working web application (deployed or local demo)
- [ ] Trained RL model for single intersection
- [ ] Comparison results: RL vs Fixed-time control
- [ ] Performance charts (waiting time, throughput over episodes)
- [ ] System architecture documentation
- [ ] Demo video (3-5 minutes)
- [ ] Source code repository

---

## 🚦 Success Criteria

1. **Functional:** User can select a region, run simulation, and control traffic lights
2. **ML Working:** RL agent shows improvement over training (decreasing waiting time)
3. **Measurable:** Dashboard displays real-time metrics from simulation
4. **Documented:** Clear setup instructions, API documentation, thesis-ready figures

---

This plan keeps scope manageable for a graduation thesis while delivering a complete, demonstrable system. Focus on getting each week's deliverable working before moving forward. Would you like me to elaborate on any specific week or component?

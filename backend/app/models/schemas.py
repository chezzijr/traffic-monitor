# Pydantic schemas for API request/response validation

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Bounding box coordinates for map region extraction."""

    south: float = Field(..., ge=-90, le=90, description="Southern latitude bound")
    west: float = Field(..., ge=-180, le=180, description="Western longitude bound")
    north: float = Field(..., ge=-90, le=90, description="Northern latitude bound")
    east: float = Field(..., ge=-180, le=180, description="Eastern longitude bound")

    def as_tuple(self) -> tuple[float, float, float, float]:
        """Return bbox as (south, west, north, east) tuple."""
        return (self.south, self.west, self.north, self.east)


class Intersection(BaseModel):
    """Road intersection node from OSM network."""

    id: str = Field(..., description="Unique intersection identifier")
    lat: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    osm_id: int = Field(..., description="OSM node ID")
    lon: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    name: str | None = Field(None, description="Street name at intersection (if available)")
    num_roads: int = Field(..., ge=1, description="Number of roads meeting at this intersection")
    has_traffic_light: bool = Field(default=False, description="Whether this intersection has a traffic light")
    sumo_tl_id: str | None = Field(None, description="SUMO traffic light ID (if converted and mapped)")
    roads: list[str] | None = Field(None, description="Names of roads meeting at this intersection (up to 2)")


class TrafficSignal(BaseModel):
    """Traffic signal node from OSM (legacy name)."""

    osm_id: int = Field(..., description="OSM node ID")
    lat: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    lon: float = Field(..., ge=-180, le=180, description="Longitude coordinate")


class TrafficLight(BaseModel):
    """Traffic light node from OSM."""

    osm_id: int = Field(..., description="OSM node ID")
    lat: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    lon: float = Field(..., ge=-180, le=180, description="Longitude coordinate")


class NetworkInfo(BaseModel):
    """Information about an extracted OSM road network."""

    network_id: str = Field(..., description="Unique network identifier")
    intersections: list[Intersection] = Field(default_factory=list, description="List of intersections")
    road_count: int = Field(..., ge=0, description="Total number of road segments")
    bbox: BoundingBox = Field(..., description="Bounding box of the network")


class TrafficScenario(str, Enum):
    """Traffic scenario for route generation."""

    LIGHT = "light"
    MODERATE = "moderate"
    HEAVY = "heavy"
    RUSH_HOUR = "rush_hour"


class MetricsSnapshotResponse(BaseModel):
    """Response model for a metrics snapshot."""

    timestamp: datetime
    step: int = Field(..., ge=0, description="Simulation step number")
    total_vehicles: int = Field(..., ge=0, description="Total number of vehicles in simulation")
    total_wait_time: float = Field(..., ge=0, description="Sum of all vehicle waiting times (seconds)")
    average_wait_time: float = Field(..., ge=0, description="Average waiting time per vehicle (seconds)")
    throughput: int = Field(..., ge=0, description="Vehicles that completed their trip")


class MetricsSummary(BaseModel):
    """Summary statistics from metrics history."""

    total_snapshots: int = Field(..., ge=0, description="Number of snapshots in history")
    avg_vehicles: float = Field(..., ge=0, description="Average number of vehicles across all snapshots")
    avg_wait_time: float = Field(..., ge=0, description="Average waiting time across all snapshots")
    total_throughput: int = Field(..., ge=0, description="Total vehicles that completed their trip")


class TrafficLightInfo(BaseModel):
    """Traffic light information and current state."""

    id: str = Field(..., description="Traffic light ID")
    phase: int = Field(..., ge=0, description="Current phase index")
    program: str = Field(..., description="Current program ID")


class SetPhaseRequest(BaseModel):
    """Request body for setting a traffic light phase."""

    phase: int = Field(..., ge=0, description="Phase index to set (0-indexed)")


class SUMOTrafficLight(BaseModel):
    """Traffic light data from SUMO network."""

    id: str = Field(..., description="SUMO traffic light ID")
    type: str = Field(..., description="Traffic light type (e.g., 'static', 'actuated')")
    program_id: str = Field(..., description="Traffic light program ID")
    num_phases: int = Field(..., ge=0, description="Number of phases in the traffic light program")


class ConvertToSumoResponse(BaseModel):
    """Response model for converting OSM network to SUMO format."""

    sumo_network_path: str = Field(..., description="Path to the generated SUMO .net.xml file")
    network_id: str = Field(..., description="Unique network identifier")
    traffic_lights: list[SUMOTrafficLight] = Field(
        default_factory=list, description="List of traffic lights in the SUMO network"
    )
    osm_sumo_mapping: dict[str, str] = Field(
        default_factory=dict, description="Mapping from OSM intersection ID to SUMO traffic light ID"
    )


class RouteGenerationRequest(BaseModel):
    """Request body for generating routes."""

    scenario: TrafficScenario = Field(default=TrafficScenario.MODERATE, description="Traffic scenario")
    duration: int = Field(default=3600, ge=60, le=86400, description="Simulation duration in seconds")
    seed: int | None = Field(default=None, description="Random seed for reproducibility")


class RouteGenerationResponse(BaseModel):
    """Response model for route generation."""

    routes_path: str = Field(..., description="Path to the generated .rou.xml file")
    trip_count: int = Field(..., ge=0, description="Estimated number of generated trips")
    vehicle_distribution: dict[str, float] = Field(..., description="Vehicle type percentages")


class TrainingRequest(BaseModel):
    """Request to start single-junction training."""

    network_id: str = Field(..., description="Network to train on")
    tl_id: str = Field(..., description="Traffic light ID to optimize")
    algorithm: str = Field(default="dqn", description="RL algorithm (dqn or ppo)")
    total_timesteps: int = Field(default=10000, ge=1000, le=1000000, description="Training timesteps")
    scenario: TrafficScenario = Field(default=TrafficScenario.MODERATE, description="Traffic scenario")


class MultiJunctionTrainingRequest(BaseModel):
    """Request to start multi-junction training."""

    network_id: str = Field(..., description="Network to train on")
    tl_ids: list[str] = Field(..., min_length=1, max_length=10, description="Traffic light IDs (max 10)")
    algorithm: str = Field(default="dqn", description="RL algorithm (dqn or ppo)")
    total_timesteps: int = Field(default=10000, ge=1000, le=1000000, description="Training timesteps")
    scenario: TrafficScenario = Field(default=TrafficScenario.MODERATE, description="Traffic scenario")


class TrainingTaskResponse(BaseModel):
    """Response after dispatching a training task."""

    task_id: str = Field(..., description="Celery task ID")
    status: str = Field(default="queued", description="Initial task status")


class TrainingProgressPayload(BaseModel):
    """Progress update from a training task."""

    task_id: str
    status: str = "running"
    timestep: int = 0
    total_timesteps: int = 0
    progress: float = 0.0
    episode_count: int = 0
    mean_reward: float = 0.0
    avg_waiting_time: float = 0.0
    avg_queue_length: float = 0.0
    throughput: int = 0
    baseline_avg_waiting_time: float | None = None
    baseline_avg_queue_length: float | None = None
    baseline_throughput: int | None = None


class TaskInfo(BaseModel):
    """Information about a Celery task."""

    task_id: str
    status: str
    network_id: str | None = None
    algorithm: str | None = None
    tl_ids: list[str] = Field(default_factory=list)
    total_timesteps: int | None = None
    progress: float = 0.0
    created_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    model_path: str | None = None


class TaskListResponse(BaseModel):
    """Response containing a list of tasks."""

    tasks: list[TaskInfo] = Field(default_factory=list)


class DeployModelRequest(BaseModel):
    """Request to deploy a trained model."""

    tl_id: str = Field(..., description="Traffic light to control")
    model_path: str = Field(..., description="Path to the trained model")
    network_id: str = Field(..., description="Network the model was trained on")


class DeployedModelInfo(BaseModel):
    """Information about a deployed model."""

    tl_id: str
    model_id: str
    model_path: str
    network_id: str
    ai_control_enabled: bool = True


class ToggleAIControlRequest(BaseModel):
    """Request to toggle AI control for a traffic light."""

    enabled: bool = Field(..., description="Whether to enable AI control")


class NetworkMetadata(BaseModel):
    """Metadata for a persisted network."""

    network_id: str
    bbox: BoundingBox
    intersection_count: int = 0
    traffic_light_count: int = 0
    created_at: datetime | None = None


class DirectionFrame(BaseModel):
    direction: str
    image: str | None  # base64


class IntersectionFrames(BaseModel):
    intersection_id: str
    frames: list[DirectionFrame]


class WaitingCountResponse(BaseModel):
    """Response model for waiting vehicle count per direction."""

    id_camera: str = Field(..., description="Camera identifier")
    north: int = Field(default=0, ge=0, description="Waiting vehicles heading north")
    south: int = Field(default=0, ge=0, description="Waiting vehicles heading south")
    east: int = Field(default=0, ge=0, description="Waiting vehicles heading east")
    west: int = Field(default=0, ge=0, description="Waiting vehicles heading west")
    total: int = Field(default=0, ge=0, description="Total waiting vehicles")
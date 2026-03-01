"""Application configuration using Pydantic Settings."""

from pathlib import Path
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # CORS settings
    cors_origins: list[str] = ["http://localhost:5173"]

    # SUMO settings
    sumo_home: Path = Path("/usr/share/sumo")

    # Simulation directory paths
    simulation_dir: Path = Path("./simulations")
    map_data_dir: Path = Path("./data/maps")

    # API settings
    api_prefix: str = "/api"
    
    # Redis settings
    redis_host: str = "localhost"
    redis_port: int = 6379
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    
    # Project root: in Docker /app/app/config.py -> parents[1] = /app
    # Locally: backend/app/config.py -> parents[2] = project root
    # Detect by checking if simulation/ exists at each level
    project_root: ClassVar[Path] = next(
        (p for p in Path(__file__).resolve().parents
         if (p / "simulation").is_dir()),
        Path(__file__).resolve().parents[2],
    )

    dataset_dir: Path = project_root / "dataset"
    simulation_networks_dir: ClassVar[Path] = project_root / "simulation" / "networks"
    simulation_models_dir: ClassVar[Path] = project_root / "simulation" / "models"
    simulation_vtypes_dir: ClassVar[Path] = project_root / "simulation" / "vtypes"


settings = Settings()

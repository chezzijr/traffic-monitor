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
    
    #Dataset settings
    project_root: ClassVar[Path] = Path(__file__).resolve().parents[2]

    dataset_dir: Path = project_root / "dataset"


settings = Settings()

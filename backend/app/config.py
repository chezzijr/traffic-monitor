"""Application configuration using Pydantic Settings."""

from pathlib import Path

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


settings = Settings()

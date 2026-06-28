"""Central configuration for the UAE Climate Mobility Platform.

All tunables live here so the rest of the codebase can stay declarative.
Values can be overridden via environment variables or a local ``.env`` file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project paths
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
CACHE_DIR = BACKEND_DIR / ".cache"
CACHE_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    """Runtime settings, populated from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Geography ---
    # Default sector to load. Any OSM-resolvable place string works.
    place: str = Field(default="Downtown Dubai, Dubai, United Arab Emirates")
    # Center used for solar / weather sampling (lat, lon).
    center_lat: float = Field(default=25.1972)
    center_lon: float = Field(default=55.2744)
    utm_epsg: int = Field(default=32640)  # UTM Zone 40N for the UAE
    timezone: str = Field(default="Asia/Dubai")
    # Radius (m) of the loaded sector around the center. 2200 m -> ~4.4x4.4 km.
    osm_radius_m: int = Field(default=2200)

    # --- Simulation ---
    agent_count: int = Field(default=24000)
    sim_fps: int = Field(default=20)
    # Comfort/air grid cell size. Coarser keeps a big area fast on CPU.
    raster_resolution_m: float = Field(default=7.0)

    # --- Thermal / physiology ---
    air_temp_c: float = Field(default=41.0)  # fallback ambient if no live data
    relative_humidity: float = Field(default=55.0)
    wind_speed_ms: float = Field(default=3.0)
    wind_dir_deg: float = Field(default=315.0)  # meteorological "from" direction

    # --- Data adapters (hybrid) ---
    openweather_api_key: str = Field(default="")
    tomtom_api_key: str = Field(default="")
    use_live_data: bool = Field(default=True)  # auto-falls back to simulation
    live_data_timeout_s: float = Field(default=4.0)
    env_refresh_s: float = Field(default=60.0)  # live weather poll interval (frontend + backend cache)

    # --- Compute ---
    force_cpu: bool = Field(default=False)  # disable GPU even if CuPy present
    force_synthetic: bool = Field(default=False)  # skip OSM, use synthetic sector

    # --- Server ---
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://127.0.0.1:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

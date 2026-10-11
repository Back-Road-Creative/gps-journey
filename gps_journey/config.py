"""Configuration management using Pydantic settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GeocodingConfig(BaseSettings):
    """Geocoding service configuration."""

    provider: Literal["nominatim", "google", "mapbox"] = "nominatim"
    rate_limit: float = 1.0  # requests per second
    cache_enabled: bool = True
    cache_path: Path = Path(".geocode_cache.json")
    cache_ttl_days: int = 90

    # Nominatim settings
    nominatim_user_agent: str = "gps-journey/0.1.0"

    # Google Maps settings
    google_api_key: str | None = None

    model_config = SettingsConfigDict(env_prefix="GEOCODING_")


class GooglePhotosConfig(BaseSettings):
    """Google Photos API configuration."""

    # OAuth credentials - prefer environment variables over file
    client_id: str | None = None
    client_secret: str | None = None
    project_id: str | None = None

    # Fallback to file-based credentials if env vars not set
    credentials_path: Path = Path("credentials.json")
    token_path: Path = Path("token.json")

    scopes: list[str] = Field(
        default_factory=lambda: ["https://www.googleapis.com/auth/photoslibrary.readonly"]
    )
    download_photos: bool = False  # Only download metadata by default

    model_config = SettingsConfigDict(env_prefix="GOOGLE_PHOTOS__")

    @property
    def has_env_credentials(self) -> bool:
        """Check if OAuth credentials are provided via environment variables."""
        return bool(self.client_id and self.client_secret)

    def get_credentials_dict(self) -> dict:
        """Get OAuth credentials as a dictionary (for InstalledAppFlow)."""
        if not self.has_env_credentials:
            raise ValueError(
                "OAuth credentials not configured. Set GOOGLE_PHOTOS__CLIENT_ID and "
                "GOOGLE_PHOTOS__CLIENT_SECRET environment variables, or provide credentials.json"
            )
        return {
            "installed": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "project_id": self.project_id or "unknown",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost"],
            }
        }


class HugoConfig(BaseSettings):
    """Hugo site integration configuration."""

    # Site locations have no default; configure them to point at your Hugo site.
    # `content_path` is set by the process environment variable
    # HUGO_CONTENT_PATH, or by HUGO__CONTENT_PATH in a `.env` file (the
    # single-underscore spelling is only read from the process environment). The
    # CLI also takes --hugo-dir, and --static-dir for the static directory.
    # Library users can pass a `hugo:` mapping through `Config.from_yaml`; the CLI
    # does not read a YAML file. `image_path`, `map_path` and `static_path` are
    # reserved: no command reads them yet, and only the --static-dir option
    # reaches HugoGenerator.
    content_path: Path | None = None
    image_path: Path | None = None
    map_path: Path | None = None
    static_path: Path | None = None
    archetype: str = "journey"

    @field_validator("content_path", "image_path", "map_path", "static_path", mode="before")
    @classmethod
    def _blank_path_is_unset(cls, value: object) -> object:
        """Treat an empty or whitespace-only value as not configured."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    # Unknown HUGO__<name> keys (for example in a `.env` shared with another tool)
    # are ignored rather than rejected.
    model_config = SettingsConfigDict(env_prefix="HUGO_", extra="ignore")


class MapsConfig(BaseSettings):
    """Map generation configuration."""

    provider: Literal["folium"] = "folium"
    tile_layer: Literal["OpenStreetMap", "OpenTopoMap", "Stamen Terrain"] = "OpenStreetMap"
    width: int = 1280
    height: int = 720

    model_config = SettingsConfigDict(env_prefix="MAPS_")


class ProcessingConfig(BaseSettings):
    """Journey processing configuration."""

    min_stop_duration_seconds: int = 300  # 5 minutes
    photo_match_tolerance_seconds: int = 300  # ±5 minutes
    waypoint_distance_threshold_meters: float = 100  # Merge nearby waypoints

    model_config = SettingsConfigDict(env_prefix="PROCESSING_")


class Config(BaseSettings):
    """Main application configuration."""

    geocoding: GeocodingConfig = Field(default_factory=GeocodingConfig)
    google_photos: GooglePhotosConfig = Field(default_factory=GooglePhotosConfig)
    hugo: HugoConfig = Field(default_factory=HugoConfig)
    maps: MapsConfig = Field(default_factory=MapsConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        # A `.env` file in the current directory may belong to another tool.
        extra="ignore",
    )

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "Config":
        """Load configuration from YAML file."""
        import yaml

        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        return cls(**data)


class HugoSettings(BaseSettings):
    """Only the Hugo section of the settings.

    Commands that need a Hugo path read this instead of the full ``Config``, so
    an unrelated invalid value in another section (for example a lower-case
    ``LOG_LEVEL`` in the process environment) cannot abort them. The same
    sources apply: ``HUGO_<NAME>`` in the environment, ``HUGO__<NAME>`` in a
    ``.env`` file in the current directory.
    """

    hugo: HugoConfig = Field(default_factory=HugoConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


def load_hugo_config() -> HugoConfig:
    """Read the Hugo section from the environment and ``.env`` as they are now."""
    return HugoSettings().hugo


def __getattr__(name: str) -> Config:
    """Build the global ``config`` on first access, not at import.

    ``from gps_journey.config import config`` still works; importing the module
    for ``load_hugo_config`` alone does not validate the other sections.
    """
    if name == "config":
        value = Config()
        globals()["config"] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

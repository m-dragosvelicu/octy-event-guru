from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    brave_search_api_key: str = Field(validation_alias="BRAVE_SEARCH_API_KEY")
    default_area_id: str = Field(default="bucharest", validation_alias="DEFAULT_AREA_ID")

    supabase_url: str = Field(default="", validation_alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(default="", validation_alias="SUPABASE_SERVICE_ROLE_KEY")
    event_guru_host_user_id: str = Field(default="", validation_alias="EVENT_GURU_HOST_USER_ID")
    ingest_api_token: str = Field(default="", validation_alias="INGEST_API_TOKEN")

    mapbox_access_token: str = Field(default="", validation_alias="MAPBOX_ACCESS_TOKEN")
    mapbox_permanent: bool = Field(default=True, validation_alias="MAPBOX_PERMANENT")
    mapbox_country_bias: str | None = Field(default=None, validation_alias="MAPBOX_COUNTRY_BIAS")
    mapbox_bbox_bias: str | None = Field(default=None, validation_alias="MAPBOX_BBOX_BIAS")
    geocode_min_score: float = 0.75

    requests_timeout_seconds: int = 15
    requests_user_agent: str = "event-guru-ingest/0.1"
    ingest_run_report_path: str = Field(
        default="ingest_runs.json",
        validation_alias="INGEST_RUN_REPORT_PATH",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_area_configs(path: str = "app/sources/areas.yaml") -> list:
    from ..domain.models import AreaConfig

    config_path = Path(path)
    if not config_path.exists():
        return []
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return [AreaConfig.model_validate(item) for item in data]

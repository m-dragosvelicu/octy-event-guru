from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str = Field(validation_alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(validation_alias="SUPABASE_SERVICE_ROLE_KEY")
    event_guru_host_user_id: str = Field(validation_alias="EVENT_GURU_HOST_USER_ID")
    mapbox_access_token: str = Field(validation_alias="MAPBOX_ACCESS_TOKEN")
    mapbox_permanent: bool = Field(default=True, validation_alias="MAPBOX_PERMANENT")
    ingest_api_token: str = Field(validation_alias="INGEST_API_TOKEN")
    default_area_id: str = Field(validation_alias="DEFAULT_AREA_ID")

    requests_timeout_seconds: int = 10
    requests_user_agent: str = "event-guru-ingest/0.1"
    geocode_min_score: float = 0.75
    ingest_run_report_path: str = Field(
        default="ingest_runs.json",
        validation_alias="INGEST_RUN_REPORT_PATH",
    )
    mapbox_country_bias: str | None = Field(default="us", validation_alias="MAPBOX_COUNTRY_BIAS")
    mapbox_bbox_bias: str | None = Field(default=None, validation_alias="MAPBOX_BBOX_BIAS")


@lru_cache
def get_settings() -> Settings:
    return Settings()

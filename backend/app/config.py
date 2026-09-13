from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    database_url: str
    anthropic_api_key: str
    contact_email: str
    target_states: str = "VA"
    propublica_search_url: str
    propublica_organization_url: str
    watchlist_path: str = "backend/watchlist.yaml"
    watchlist_hashes_path: str = "backend/watchlist_hashes.json"
    directories_path: str = "backend/directories.yaml"
    google_places_api_key: str = ""
    google_places_search_url: str = ""
    google_places_grid: str = ""
    reachinbox_api_key: str = ""
    reachinbox_base_url: str = "https://api.reachinbox.ai"
    apollo_api_key: str = ""
    apollo_base_url: str = "https://api.apollo.io"
    hunter_api_key: str = ""
    hunter_base_url: str = "https://api.hunter.io"


@lru_cache
def get_settings() -> Settings:
    return Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    gemini_model_flash: str = "gemini-2.5-flash-lite"
    gemini_model_pro: str = "gemini-2.5-flash"

    db_path: str = ".data/youtubesynth.db"
    cache_dir: str = ".cache/transcripts"
    output_dir: str = "output"
    summaries_dir: str = "summaries"

    max_videos_per_job: int = 50
    default_concurrency: int = 3
    chunk_token_threshold: int = 8000


settings = Settings()

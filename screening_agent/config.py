from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Model ids are bake-off outputs; override via SCREENING_* env vars rather than editing code."""

    model_config = SettingsConfigDict(env_prefix="SCREENING_", env_file=".env", extra="ignore")

    live_model: str = "anthropic:claude-sonnet-5-5"
    summary_model: str = "anthropic:claude-haiku-5-5"
    guardrail_model: str = "anthropic:claude-haiku-5-5"
    llm_timeout_seconds: float = 15.0
    llm_max_retries: int = 2
    reask_limit: int = 2
    database_url: str = "sqlite:///data/screening.db"
    assistant_name: str = "Sazón"
    # Candidate-facing dates use the service area's zone once known; this covers the stages before it.
    default_timezone: str = "Europe/Madrid"
    recruiter_api_key: str | None = None
    twilio_auth_token: str | None = None
    # Twilio signs the URL configured in its console; set this when a proxy rewrites the request URL.
    twilio_webhook_url: str | None = None
    # Only dev mode lets the API run without a recruiter key or webhook secret.
    dev_mode: bool = False


settings = Settings()

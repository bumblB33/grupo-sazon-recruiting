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
    database_url: str = "mongodb://localhost:27017/screening"
    assistant_name: str = "Sazón"
    # Candidate-facing dates use the service area's zone once known; this covers the stages before it.
    default_timezone: str = "Europe/Madrid"
    recruiter_api_key: str | None = None
    twilio_auth_token: str | None = None
    # Twilio signs the URL configured in its console; set this when a proxy rewrites the request URL.
    twilio_webhook_url: str | None = None
    # Outbound WhatsApp (opener and nudges) via the Twilio Messages REST API.
    twilio_account_sid: str | None = None
    twilio_whatsapp_from: str | None = None
    # Only an approved template is deliverable outside the 24h window; unset sends plain text (sandbox).
    twilio_opener_content_sid: str | None = None
    # Hours since the opener (before any reply) or since the candidate's last message (after one).
    opener_retry_hours: list[float] = [24.0]
    opener_abandon_hours: float = 48.0
    silence_nudge_hours: list[float] = [2.0, 23.0]
    silence_abandon_hours: float = 24.0
    # Only dev mode lets the API run without a recruiter key or webhook secret.
    dev_mode: bool = False


settings = Settings()

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Model ids are bake-off outputs; override via SCREENING_* env vars rather than editing code."""

    model_config = SettingsConfigDict(
        env_prefix="SCREENING_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    live_model: str = "anthropic:claude-sonnet-5-5"
    summary_model: str = "anthropic:claude-haiku-5-5"
    guardrail_model: str = "anthropic:claude-haiku-5-5"
    # Not ANTHROPIC_API_KEY: Claude Code in the same terminal reads that name and would bill the key.
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias="PROJECT_ANTHROPIC_API_KEY"
    )
    # An org-level Anthropic key is not scoped to a workspace; the API then requires this id on every request.
    anthropic_workspace_id: str | None = Field(
        default=None, validation_alias="PROJECT_ANTHROPIC_WORKSPACE_ID"
    )
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    mistral_api_key: SecretStr | None = Field(default=None, validation_alias="MISTRAL_API_KEY")
    llm_timeout_seconds: float = 15.0
    llm_max_retries: int = 2
    reask_limit: int = 2
    # Similarity (0 to 1) between the name the candidate gives and the applicant name below which
    # the agent asks the candidate to confirm who they are.
    name_match_threshold: float = 0.8
    max_unanswered_agent_messages: int = 2
    database_url: str = "mongodb://localhost:27017/screening"
    # Separate from database_url so evals never write to, or drop databases on, the app's cluster.
    eval_database_url: str = "mongodb://localhost:27017/screening"
    assistant_name: str = "Sazón"
    # Candidate-facing dates use the service area's zone once known; this covers the stages before it.
    default_timezone: str = "Europe/Madrid"
    # Signs the recruiter session cookie; rotating it logs every recruiter out once.
    session_secret: SecretStr | None = None
    session_hours: float = 12.0
    login_link_minutes: float = 15.0
    # Second gate after the invite: a recruiter must be invited and at one of these domains.
    recruiter_email_domains: list[str] = []
    # Base URL the login link points at. Required outside dev mode: the Host header is attacker-controlled.
    public_url: str | None = None
    # One login email per address per cooldown, and at most this many per client IP per window.
    login_email_cooldown_seconds: float = 60.0
    login_requests_per_ip: int = 30
    login_ip_window_minutes: float = 60.0
    # Login links go out through Twilio SendGrid.
    sendgrid_api_key: SecretStr | None = None
    login_email_from: str | None = None
    # Dev mode only: every login email is delivered to this address instead of the recruiter's,
    # so a demo can type a company address and still receive the link.
    login_email_redirect_to: str | None = None
    twilio_auth_token: SecretStr | None = None
    # Twilio signs the URL configured in its console; set this when a proxy rewrites the request URL.
    twilio_webhook_url: str | None = None
    # Outbound WhatsApp (opener and nudges) via the Twilio Messages REST API.
    # Twilio recommends an API key over the auth token for REST; the auth token still signs webhooks.
    twilio_account_sid: str | None = None
    twilio_api_key_sid: str | None = None
    twilio_api_key_secret: SecretStr | None = None
    twilio_whatsapp_from: str | None = None
    # Only an approved template is deliverable outside the 24h window; unset sends plain text (sandbox).
    twilio_opener_content_sid: str | None = None
    # Hours since the opener (before any reply) or since the candidate's last message (after one).
    opener_retry_hours: list[float] = [24.0]
    opener_abandon_hours: float = 48.0
    silence_nudge_hours: list[float] = [2.0, 23.0]
    silence_abandon_hours: float = 24.0
    # Logfire reads LOGFIRE_TOKEN from the process env only, and pydantic-settings does not export .env.
    logfire_token: SecretStr | None = None
    # Keys the candidate hash in traces; a plain hash of a phone number is reversible by enumeration.
    candidate_hash_secret: SecretStr | None = None
    # The recruiter candidate page reloads itself at this interval while the conversation is open; 0 disables it.
    candidate_page_refresh_seconds: int = 5
    # Only dev mode lets the API run without a recruiter key or webhook secret.
    dev_mode: bool = False
    # Candidate ids a recruiter may archive and reopen from the console. Separate from dev_mode so
    # no real candidate can be reset by a stray flag.
    demo_phones: list[str] = []


settings = Settings()

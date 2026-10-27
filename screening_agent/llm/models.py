from dataclasses import dataclass

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from screening_agent.config import settings


@dataclass(frozen=True)
class Provider:
    key_setting: str
    env_var: str
    temperature: float | None


# pydantic-settings reads .env without exporting it, so LangChain only sees these keys if we pass them.
# Anthropic and OpenAI reject sampling parameters on current models (GPT-6 accepts only the default
# temperature). Providers absent here (bedrock, vertex) authenticate with cloud credentials and get
# no key or sampling parameters.
PROVIDERS = {
    "anthropic": Provider("anthropic_api_key", "PROJECT_ANTHROPIC_API_KEY", None),
    "openai": Provider("openai_api_key", "OPENAI_API_KEY", None),
    "mistralai": Provider("mistral_api_key", "MISTRAL_API_KEY", 0),
}
BARE_ID_PROVIDERS = (("claude", "anthropic"), ("gpt-", "openai"), ("mistral", "mistralai"))


class ProviderKeyMissingError(RuntimeError):
    """Raised instead of letting LangChain fall back to a shell variable, which may hold another account's key."""


def chat_model(model_id: str) -> BaseChatModel:
    """One constructor so the bake-off swaps ids, not call sites."""
    options: dict = {
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,
    }
    provider = PROVIDERS.get(_provider(model_id))
    if provider is not None:
        key = getattr(settings, provider.key_setting)
        if key is None:
            raise ProviderKeyMissingError(f"{provider.env_var} is required for {model_id}")
        options["api_key"] = key
        if provider.temperature is not None:
            options["temperature"] = provider.temperature
    if provider is PROVIDERS["anthropic"] and settings.anthropic_workspace_id:
        options["default_headers"] = {"anthropic-workspace-id": settings.anthropic_workspace_id}
    return init_chat_model(model_id, **options)


def _provider(model_id: str) -> str | None:
    provider, separator, _ = model_id.partition(":")
    if separator:
        return provider
    return next((name for prefix, name in BARE_ID_PROVIDERS if model_id.startswith(prefix)), None)

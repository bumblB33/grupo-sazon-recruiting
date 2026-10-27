import pytest
from pydantic import SecretStr

from screening_agent.config import Settings, settings
from screening_agent.llm import models
from screening_agent.llm.models import ProviderKeyMissingError, chat_model


def test_anthropic_model_uses_project_key_not_the_shell_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "shell-key")
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("project-key"))
    model = chat_model("anthropic:claude-haiku-5-5")
    assert model.anthropic_api_key.get_secret_value() == "project-key"
    assert model.temperature is None


def test_anthropic_model_without_project_key_fails_closed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "shell-key")
    with pytest.raises(ProviderKeyMissingError, match="PROJECT_ANTHROPIC_API_KEY"):
        chat_model("claude-haiku-5-5")


def test_openai_and_mistral_keys_come_from_settings_not_only_the_shell(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("openai-from-env-file"))
    monkeypatch.setattr(settings, "mistral_api_key", SecretStr("mistral-from-env-file"))
    openai = chat_model("openai:gpt-6-luna")
    mistral = chat_model("mistralai:mistral-small-latest")
    assert openai.openai_api_key.get_secret_value() == "openai-from-env-file"
    assert mistral.mistral_api_key.get_secret_value() == "mistral-from-env-file"
    assert openai.temperature is None and mistral.temperature == 0


def test_missing_provider_key_names_the_env_var():
    with pytest.raises(ProviderKeyMissingError, match="OPENAI_API_KEY"):
        chat_model("gpt-6-luna")
    with pytest.raises(ProviderKeyMissingError, match="MISTRAL_API_KEY"):
        chat_model("mistralai:mistral-small-latest")


def test_claude_on_bedrock_gets_no_sampling_parameters_and_no_anthropic_key(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        models, "init_chat_model", lambda model_id, **options: captured.update(options)
    )
    chat_model("bedrock_converse:us.anthropic.claude-haiku-5-5-v1:0")
    assert "temperature" not in captured and "api_key" not in captured


def test_empty_env_assignment_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("SCREENING_SESSION_SECRET", "")
    fresh = Settings(_env_file=None)
    assert fresh.openai_api_key is None and fresh.session_secret is None


def test_anthropic_model_sends_workspace_header_only_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("project-key"))
    assert chat_model("anthropic:claude-haiku-5-5").default_headers is None
    monkeypatch.setattr(settings, "anthropic_workspace_id", "wrkspc_test")
    model = chat_model("anthropic:claude-haiku-5-5")
    assert model.default_headers == {"anthropic-workspace-id": "wrkspc_test"}
    assert model._client.default_headers["anthropic-workspace-id"] == "wrkspc_test"

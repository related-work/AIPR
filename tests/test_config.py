from __future__ import annotations

from ai_pr_review.config import (
    ReviewConfig,
    load_config,
    resolve_github_token,
    resolve_openai_api_key,
    resolve_openai_api_mode,
    resolve_openai_base_url,
)
from ai_pr_review.llm import select_models


def test_load_config_merges_public_config_with_local_private_config(tmp_path) -> None:
    public_config = tmp_path / ".ai-pr-review.yml"
    local_config = tmp_path / ".ai-pr-review.local.yml"
    public_config.write_text(
        """
models:
  fast: public-fast
  strong: public-strong
review:
  fail_on: high
  ignore_paths:
    - dist/**
rules:
  require_tests_for:
    - src/payment/**
""",
        encoding="utf-8",
    )
    local_config.write_text(
        """
credentials:
  github_token: local-gh-token
  openai_api_key: local-oa-key
models:
  fast: local-fast
openai:
  api_key: local-openai-api-key
  model: local-openai-model
  base_url: https://local-openai.example/v1
  api_mode: chat
  timeout_seconds: 12.5
review:
  max_llm_chunks: 3
""",
        encoding="utf-8",
    )

    config = load_config(public_config, local_config)

    assert config.credentials.github_token == "local-gh-token"
    assert config.credentials.openai_api_key == "local-oa-key"
    assert config.openai.api_key == "local-openai-api-key"
    assert config.openai.model == "local-openai-model"
    assert config.openai.base_url == "https://local-openai.example/v1"
    assert config.openai.api_mode == "chat"
    assert config.openai.timeout_seconds == 12.5
    assert config.models.fast == "local-fast"
    assert config.models.strong == "public-strong"
    assert config.review.fail_on == "high"
    assert config.review.ignore_paths == ["dist/**"]
    assert config.review.max_llm_chunks == 3
    assert config.rules.require_tests_for == ["src/payment/**"]


def test_environment_credentials_take_priority_over_local_config(monkeypatch) -> None:
    config = ReviewConfig.from_mapping(
        {
            "credentials": {
                "github_token": "file-gh-token",
                "openai_api_key": "file-oa-key",
            },
            "openai": {
                "api_key": "file-openai-api-key",
                "base_url": "https://file.example/v1",
                "api_mode": "responses",
            },
        }
    )
    monkeypatch.setenv("GITHUB_TOKEN", "env-gh-token")
    monkeypatch.setenv("OPENAI_API_KEY", "env-oa-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("OPENAI_API_MODE", "chat")

    assert resolve_github_token(config) == "env-gh-token"
    assert resolve_openai_api_key(config) == "env-oa-key"
    assert resolve_openai_base_url(config) == "https://env.example/v1"
    assert resolve_openai_api_mode(config) == "chat"


def test_openai_config_can_provide_api_key_base_url_and_single_model(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_FAST_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_STRONG_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    config = ReviewConfig.from_mapping(
        {
            "models": {"fast": "config-fast", "strong": "config-strong"},
            "openai": {
                "api_key": "local-api-key",
                "base_url": "https://compatible.example/v1",
                "model": "compatible-model",
            },
        }
    )

    assert resolve_openai_api_key(config) == "local-api-key"
    assert resolve_openai_base_url(config) == "https://compatible.example/v1"
    assert select_models(config, "balanced") == ("compatible-model", "compatible-model")


def test_openai_model_environment_variable_overrides_file_model(monkeypatch) -> None:
    config = ReviewConfig.from_mapping(
        {
            "openai": {"model": "file-model"},
            "models": {"fast": "file-fast", "strong": "file-strong"},
        }
    )
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    monkeypatch.delenv("OPENAI_FAST_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_STRONG_MODEL", raising=False)

    assert select_models(config, "balanced") == ("env-model", "env-model")


def test_specific_openai_model_environment_variables_override_single_model(monkeypatch) -> None:
    config = ReviewConfig.from_mapping({"openai": {"model": "file-model"}})
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    monkeypatch.setenv("OPENAI_FAST_MODEL", "env-fast")
    monkeypatch.setenv("OPENAI_STRONG_MODEL", "env-strong")

    assert select_models(config, "balanced") == ("env-fast", "env-strong")


def test_openai_api_mode_defaults_to_auto(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_MODE", raising=False)
    config = ReviewConfig()

    assert resolve_openai_api_mode(config) == "auto"

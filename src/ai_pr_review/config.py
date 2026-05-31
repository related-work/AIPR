from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class ModelSettings(BaseModel):
    fast: str = "gpt-5.4-mini"
    strong: str = "gpt-5.5"


class ReviewSettings(BaseModel):
    fail_on: str | None = None
    ignore_paths: list[str] = Field(default_factory=list)
    high_risk_paths: list[str] = Field(default_factory=list)
    max_files: int | None = None
    max_chunks: int | None = None
    max_llm_chunks: int | None = None
    max_context_files: int | None = None
    max_patch_lines_per_chunk: int | None = None
    large_pr_file_threshold: int = 30
    large_pr_line_threshold: int = 3000


class RuleSettings(BaseModel):
    require_tests_for: list[str] = Field(default_factory=list)


class CredentialSettings(BaseModel):
    github_token: str | None = None
    openai_api_key: str | None = None


class OpenAISettings(BaseModel):
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_mode: Literal["auto", "responses", "chat"] = "auto"
    timeout_seconds: float = 45.0


class ReviewConfig(BaseModel):
    models: ModelSettings = Field(default_factory=ModelSettings)
    review: ReviewSettings = Field(default_factory=ReviewSettings)
    rules: RuleSettings = Field(default_factory=RuleSettings)
    credentials: CredentialSettings = Field(default_factory=CredentialSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "ReviewConfig":
        return cls.model_validate(data or {})


def load_config(
    path: str | Path = ".ai-pr-review.yml",
    local_path: str | Path | None = ".ai-pr-review.local.yml",
) -> ReviewConfig:
    data = _read_yaml_mapping(Path(path))
    if local_path is not None:
        local_data = _read_yaml_mapping(Path(local_path))
        data = _deep_merge(data, local_data)
    return ReviewConfig.from_mapping(data)


def resolve_github_token(config: ReviewConfig) -> str | None:
    return os.getenv("GITHUB_TOKEN") or config.credentials.github_token


def resolve_openai_api_key(config: ReviewConfig) -> str | None:
    return (
        os.getenv("OPENAI_API_KEY")
        or config.openai.api_key
        or config.credentials.openai_api_key
    )


def resolve_openai_base_url(config: ReviewConfig) -> str | None:
    return os.getenv("OPENAI_BASE_URL") or config.openai.base_url


def resolve_openai_api_mode(config: ReviewConfig) -> str:
    raw = os.getenv("OPENAI_API_MODE") or config.openai.api_mode
    if raw not in {"auto", "responses", "chat"}:
        raise ValueError("OPENAI_API_MODE must be one of: auto, responses, chat")
    return raw


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ModelSettings(BaseModel):
    fast: str = "gpt-5.4-mini"
    strong: str = "gpt-5.5"


class ReviewSettings(BaseModel):
    fail_on: str | None = None
    ignore_paths: list[str] = Field(default_factory=list)
    high_risk_paths: list[str] = Field(default_factory=list)


class RuleSettings(BaseModel):
    require_tests_for: list[str] = Field(default_factory=list)


class ReviewConfig(BaseModel):
    models: ModelSettings = Field(default_factory=ModelSettings)
    review: ReviewSettings = Field(default_factory=ReviewSettings)
    rules: RuleSettings = Field(default_factory=RuleSettings)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "ReviewConfig":
        return cls.model_validate(data or {})


def load_config(path: str | Path = ".ai-pr-review.yml") -> ReviewConfig:
    config_path = Path(path)
    if not config_path.exists():
        return ReviewConfig()
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{config_path} must contain a YAML mapping")
    return ReviewConfig.from_mapping(data)

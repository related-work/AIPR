from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from ai_pr_review.config import ReviewConfig
from ai_pr_review.llm import LLMError, _call_structured, _create_client, select_models


SmokeTester = Callable[..., tuple[bool, str | None, list[str]]]


class DoctorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    github_token_configured: bool
    openai_api_key_configured: bool
    openai_base_url_configured: bool
    openai_base_url_status: str
    api_mode: str
    fast_model: str
    strong_model: str
    smoke_ok: bool
    smoke_error: str | None
    warnings: list[str]
    limitations: list[str]


def run_doctor(
    *,
    config: ReviewConfig,
    github_token: str | None,
    openai_api_key: str | None,
    openai_base_url: str | None,
    api_mode: str,
    model_profile: str,
    smoke: bool,
    smoke_tester: SmokeTester | None = None,
) -> DoctorReport:
    fast_model, strong_model = select_models(config, model_profile)
    warnings: list[str] = []
    limitations: list[str] = []
    base_url_status = _base_url_status(openai_base_url)
    if base_url_status == "configured_maybe_web_root":
        warnings.append(
            "OPENAI_BASE_URL 已配置但不像 API endpoint；One API/OpenAI 兼容网关通常需要以 /v1 结尾"
        )

    smoke_ok = False
    smoke_error: str | None = None
    if not smoke:
        limitations.append("已跳过 LLM smoke test")
    elif not openai_api_key:
        smoke_error = "未设置 OPENAI_API_KEY，无法执行 LLM smoke test"
    else:
        tester = smoke_tester or _smoke_test_llm
        smoke_ok, smoke_error, smoke_limitations = tester(
            model=fast_model,
            api_key=openai_api_key,
            base_url=openai_base_url,
            api_mode=api_mode,
            timeout_seconds=config.openai.timeout_seconds,
        )
        limitations.extend(smoke_limitations)

    warnings_verified_by_smoke = bool(warnings) and smoke and smoke_ok
    ok = (
        bool(openai_api_key)
        and (smoke_ok if smoke else True)
        and (not warnings or warnings_verified_by_smoke)
    )
    return DoctorReport(
        ok=ok,
        github_token_configured=bool(github_token),
        openai_api_key_configured=bool(openai_api_key),
        openai_base_url_configured=bool(openai_base_url),
        openai_base_url_status=base_url_status,
        api_mode=api_mode,
        fast_model=fast_model,
        strong_model=strong_model,
        smoke_ok=smoke_ok,
        smoke_error=smoke_error,
        warnings=warnings,
        limitations=limitations,
    )


def render_doctor_markdown(report: DoctorReport) -> str:
    lines = [
        "# AI PR Review Doctor",
        "",
        f"- 状态：{'通过' if report.ok else '未通过'}",
        f"- GitHub token：{'已配置' if report.github_token_configured else '未配置'}",
        f"- OpenAI API key：{'已配置' if report.openai_api_key_configured else '未配置'}",
        f"- OpenAI base URL：{_base_url_text(report.openai_base_url_status)}",
        f"- API mode：{report.api_mode}",
        f"- fast model：{report.fast_model}",
        f"- strong model：{report.strong_model}",
        f"- LLM smoke test：{'通过' if report.smoke_ok else '未通过'}",
    ]
    if report.smoke_error:
        lines.append(f"- smoke error：{report.smoke_error}")
    if report.warnings:
        lines.extend(["", "## 警告", ""])
        lines.extend(f"- {item}" for item in report.warnings)
    if report.limitations:
        lines.extend(["", "## 限制", ""])
        lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def render_doctor_json(report: DoctorReport) -> str:
    payload = {
        "ok": report.ok,
        "githubTokenConfigured": report.github_token_configured,
        "openaiApiKeyConfigured": report.openai_api_key_configured,
        "openaiBaseUrlConfigured": report.openai_base_url_configured,
        "openaiBaseUrlStatus": report.openai_base_url_status,
        "apiMode": report.api_mode,
        "fastModel": report.fast_model,
        "strongModel": report.strong_model,
        "smokeOk": report.smoke_ok,
        "smokeError": report.smoke_error,
        "warnings": report.warnings,
        "limitations": report.limitations,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _smoke_test_llm(
    *,
    model: str,
    api_key: str,
    base_url: str | None,
    api_mode: str,
    timeout_seconds: float,
) -> tuple[bool, str | None, list[str]]:
    try:
        client = _create_client(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
        result = _call_structured(
            client,
            model=model,
            system="Return only JSON.",
            user='Return exactly this JSON object: {"summary":"ok","findings":[]}',
            api_mode=api_mode,
        )
    except LLMError as exc:
        return False, str(exc), []
    except Exception as exc:
        return False, f"LLM smoke test 调用失败: {exc}", []
    if result.payload.get("summary") != "ok":
        return True, None, [
            *result.limitations,
            "LLM smoke test 已连通并返回可解析 JSON，但内容不完全符合预期",
        ]
    return True, None, result.limitations


def _base_url_status(base_url: str | None) -> str:
    if not base_url:
        return "default"
    stripped = base_url.rstrip("/")
    if stripped.endswith("/v1"):
        return "configured_api_like"
    return "configured_maybe_web_root"


def _base_url_text(status: str) -> str:
    if status == "default":
        return "未配置，使用 SDK 默认地址"
    if status == "configured_api_like":
        return "已配置，形态像 API endpoint"
    return "已配置，但可能是网页根地址"

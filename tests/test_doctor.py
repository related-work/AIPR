from __future__ import annotations

from ai_pr_review import doctor as doctor_module
from ai_pr_review.config import ReviewConfig
from ai_pr_review.doctor import DoctorReport, render_doctor_json, render_doctor_markdown, run_doctor
from ai_pr_review.llm import LLMCallResult


def test_run_doctor_skips_smoke_without_api_key() -> None:
    report = run_doctor(
        config=ReviewConfig(),
        github_token=None,
        openai_api_key=None,
        openai_base_url=None,
        api_mode="chat",
        model_profile="balanced",
        smoke=True,
        smoke_tester=lambda **_: (True, None, []),
    )

    assert report.ok is False
    assert report.openai_api_key_configured is False
    assert report.smoke_ok is False
    assert report.smoke_error == "未设置 OPENAI_API_KEY，无法执行 LLM smoke test"


def test_run_doctor_reports_smoke_success_without_exposing_secret_values() -> None:
    report = run_doctor(
        config=ReviewConfig(),
        github_token="ghp_secret",
        openai_api_key="sk_secret",
        openai_base_url="https://one-api.example.com/v1",
        api_mode="chat",
        model_profile="balanced",
        smoke=True,
        smoke_tester=lambda **_: (True, None, ["Chat Completions 返回非标准 JSON，已尝试从文本中提取 JSON"]),
    )

    markdown = render_doctor_markdown(report)
    payload = render_doctor_json(report)

    assert report.ok is True
    assert report.github_token_configured is True
    assert report.openai_api_key_configured is True
    assert report.openai_base_url_status == "configured_api_like"
    assert "ghp_secret" not in markdown
    assert "sk_secret" not in markdown
    assert "one-api.example.com" not in markdown
    assert "Chat Completions 返回非标准 JSON" in markdown
    assert "sk_secret" not in payload


def test_run_doctor_warns_when_base_url_does_not_look_like_api_endpoint() -> None:
    report = run_doctor(
        config=ReviewConfig(),
        github_token=None,
        openai_api_key="sk_secret",
        openai_base_url="https://one-api.example.com",
        api_mode="chat",
        model_profile="balanced",
        smoke=False,
        smoke_tester=lambda **_: (True, None, []),
    )

    assert report.ok is False
    assert report.openai_base_url_status == "configured_maybe_web_root"
    assert any("OPENAI_BASE_URL" in item for item in report.warnings)


def test_run_doctor_allows_non_v1_base_url_when_smoke_succeeds() -> None:
    report = run_doctor(
        config=ReviewConfig(),
        github_token=None,
        openai_api_key="sk_secret",
        openai_base_url="https://one-api.example.com",
        api_mode="chat",
        model_profile="balanced",
        smoke=True,
        smoke_tester=lambda **_: (True, None, []),
    )

    assert report.ok is True
    assert report.openai_base_url_status == "configured_maybe_web_root"
    assert any("OPENAI_BASE_URL" in item for item in report.warnings)


def test_smoke_test_accepts_parseable_json_with_unexpected_content(monkeypatch) -> None:
    monkeypatch.setattr(doctor_module, "_create_client", lambda **_: object())
    monkeypatch.setattr(
        doctor_module,
        "_call_structured",
        lambda *_, **__: LLMCallResult(payload={"findings": []}, limitations=[]),
    )

    ok, error, limitations = doctor_module._smoke_test_llm(
        model="compatible-model",
        api_key="sk_secret",
        base_url="https://one-api.example.com/v1",
        api_mode="chat",
        timeout_seconds=30,
    )

    assert ok is True
    assert error is None
    assert limitations == ["LLM smoke test 已连通并返回可解析 JSON，但内容不完全符合预期"]


def test_render_doctor_json_is_machine_readable() -> None:
    report = DoctorReport(
        ok=True,
        github_token_configured=False,
        openai_api_key_configured=True,
        openai_base_url_configured=True,
        openai_base_url_status="configured_api_like",
        api_mode="chat",
        fast_model="fast-model",
        strong_model="strong-model",
        smoke_ok=True,
        smoke_error=None,
        warnings=[],
        limitations=[],
    )

    assert '"ok": true' in render_doctor_json(report)
    assert '"fastModel": "fast-model"' in render_doctor_json(report)

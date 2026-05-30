from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Iterable

from openai import OpenAI
from pydantic import ValidationError

from ai_pr_review.config import ReviewConfig
from ai_pr_review.context import RetrievedContext
from ai_pr_review.diff_parser import DiffChunk
from ai_pr_review.prompts import (
    CHUNK_ANALYSIS_JSON_SCHEMA,
    REVIEW_SYSTEM_PROMPT,
    VERIFY_SYSTEM_PROMPT,
    build_chunk_prompt,
    build_verify_prompt,
)
from ai_pr_review.schemas import ChunkAnalysis, Finding


class LLMError(RuntimeError):
    """Raised for user-facing LLM failures."""


@dataclass(frozen=True)
class LLMCallResult:
    payload: dict
    limitations: list[str] = field(default_factory=list)


def select_models(config: ReviewConfig, profile: str) -> tuple[str, str]:
    single_model = os.getenv("OPENAI_MODEL") or config.openai.model
    fast = os.getenv("OPENAI_FAST_MODEL") or single_model or config.models.fast
    strong = os.getenv("OPENAI_STRONG_MODEL") or single_model or config.models.strong
    if profile == "fast":
        return fast, fast
    if profile == "accurate":
        return strong, strong
    return fast, strong


def analyze_chunks(
    chunks: Iterable[DiffChunk],
    *,
    pr_summary: str,
    context: RetrievedContext,
    comments_summary: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    api_mode: str = "auto",
    timeout_seconds: float = 45.0,
    enabled: bool = True,
) -> tuple[list[Finding], list[str]]:
    if not enabled:
        return [], ["已按配置跳过 LLM 分析，仅输出规则引擎结果"]
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return [], ["未设置 OPENAI_API_KEY，已跳过 LLM 分析，仅输出规则引擎结果"]

    findings: list[Finding] = []
    limitations: list[str] = []
    client = _create_client(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    for chunk in chunks:
        try:
            analysis, call_limitations = _analyze_chunk(
                client,
                model=model,
                pr_summary=pr_summary,
                chunk=chunk,
                context=context,
                comments_summary=comments_summary,
                api_mode=api_mode,
            )
            limitations.extend(call_limitations)
        except LLMError as exc:
            limitations.append(str(exc))
            continue
        findings.extend(
            finding.model_copy(update={"source": "llm", "rule_id": None})
            for finding in analysis.findings
        )
    return findings, limitations


def verify_high_risk_findings(
    findings: list[Finding],
    *,
    context: RetrievedContext,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    api_mode: str = "auto",
    timeout_seconds: float = 45.0,
    enabled: bool = True,
) -> tuple[list[Finding], list[str]]:
    if not enabled:
        return _local_verify(findings), []
    high_risk = [
        finding
        for finding in findings
        if finding.severity in {"critical", "high"} and finding.confidence >= 0.75
    ]
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not high_risk or not api_key:
        return _local_verify(findings), []

    client = _create_client(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    candidate_json = json.dumps(
        [finding.model_dump() for finding in high_risk],
        ensure_ascii=False,
        indent=2,
    )
    try:
        response = _call_structured(
            client,
            model=model,
            system=VERIFY_SYSTEM_PROMPT,
            user=build_verify_prompt(candidate_json, context),
            api_mode=api_mode,
        )
        verified = ChunkAnalysis.model_validate(response.payload).findings
    except (LLMError, ValidationError) as exc:
        return _local_verify(findings), [f"高风险 LLM 复核失败，已使用本地校验降级处理: {exc}"]

    verified_keys = {(item.path, item.line, item.category) for item in verified if item.evidence}
    result: list[Finding] = []
    for finding in findings:
        key = (finding.path, finding.line, finding.category)
        if finding in high_risk and key not in verified_keys:
            continue
        result.append(finding)
    return _local_verify(result), []


def _analyze_chunk(
    client: OpenAI,
    *,
    model: str,
    pr_summary: str,
    chunk: DiffChunk,
    context: RetrievedContext,
    comments_summary: str,
    api_mode: str = "auto",
) -> tuple[ChunkAnalysis, list[str]]:
    result = _call_structured(
        client,
        model=model,
        system=REVIEW_SYSTEM_PROMPT,
        user=build_chunk_prompt(
            pr_summary=pr_summary,
            chunk=chunk,
            context=context,
            comments_summary=comments_summary,
        ),
        api_mode=api_mode,
    )
    try:
        return ChunkAnalysis.model_validate(result.payload), result.limitations
    except ValidationError as exc:
        raise LLMError("LLM 返回结构不符合 schema，已跳过该 chunk") from exc


def _create_client(
    *,
    api_key: str,
    base_url: str | None,
    timeout_seconds: float,
) -> OpenAI:
    kwargs = {"api_key": api_key, "timeout": timeout_seconds}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _call_structured(
    client: OpenAI,
    *,
    model: str,
    system: str,
    user: str,
    api_mode: str = "auto",
) -> LLMCallResult:
    if api_mode == "responses":
        return _call_responses(client, model=model, system=system, user=user)
    if api_mode == "chat":
        return _call_chat(client, model=model, system=system, user=user)
    if api_mode != "auto":
        raise LLMError("api_mode 必须是 auto、responses 或 chat")

    try:
        return _call_responses(client, model=model, system=system, user=user)
    except LLMError as responses_error:
        try:
            chat_result = _call_chat(client, model=model, system=system, user=user)
        except LLMError as chat_error:
            raise LLMError(
                "Responses API 与 Chat Completions 均调用失败: "
                f"responses={responses_error}; chat={chat_error}"
            ) from chat_error
        return LLMCallResult(
            payload=chat_result.payload,
            limitations=[
                f"Responses API 调用失败，已降级到 Chat Completions: {responses_error}",
                *chat_result.limitations,
            ],
        )


def _call_responses(client: OpenAI, *, model: str, system: str, user: str) -> LLMCallResult:
    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "chunk_analysis",
                    "strict": True,
                    "schema": CHUNK_ANALYSIS_JSON_SCHEMA,
                }
            },
        )
    except Exception as exc:
        raise LLMError(f"OpenAI Responses API 调用失败: {exc}") from exc

    text = _response_output_text(response)
    if not text:
        raise LLMError("OpenAI Responses API 未返回可解析文本")
    return LLMCallResult(payload=_parse_json_object(text))


def _call_chat(client: OpenAI, *, model: str, system: str, user: str) -> LLMCallResult:
    limitations: list[str] = []
    try:
        text = _call_chat_once(
            client,
            model=model,
            system=system,
            user=user,
            use_response_format=True,
        )
    except Exception as exc:
        limitations.append(
            f"Chat Completions 不支持 response_format 或调用失败，已使用纯文本 JSON 提示: {exc}"
        )
        try:
            text = _call_chat_once(
                client,
                model=model,
                system=system,
                user=user,
                use_response_format=False,
            )
        except Exception as fallback_exc:
            raise LLMError(f"Chat Completions 调用失败: {fallback_exc}") from fallback_exc

    return LLMCallResult(payload=_parse_json_object(text), limitations=limitations)


def _call_chat_once(
    client: OpenAI,
    *,
    model: str,
    system: str,
    user: str,
    use_response_format: bool,
) -> str:
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if use_response_format:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    text = _chat_output_text(response)
    if not text:
        raise LLMError("Chat Completions 未返回可解析文本")
    return text


def _response_output_text(response) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return str(text)
    try:
        return str(response.output[0].content[0].text)
    except Exception:
        return ""


def _chat_output_text(response) -> str:
    if isinstance(response, dict):
        response = _to_object(response)
    text = getattr(response, "output_text", None)
    if text:
        return str(text)
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    choice = choices[0]
    if isinstance(choice, dict):
        choice = _to_object(choice)
    message = getattr(choice, "message", None)
    if isinstance(message, dict):
        message = _to_object(message)
    content = getattr(message, "content", None) if message is not None else None
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(getattr(item, "text", "")))
        return "".join(parts)
    if content:
        return str(content)
    text = getattr(choice, "text", None)
    return str(text or "")


def _to_object(value: dict):
    class ObjectView:
        pass

    obj = ObjectView()
    for key, item in value.items():
        setattr(obj, key, _to_object(item) if isinstance(item, dict) else item)
    return obj


def _parse_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMError("LLM 返回了非 JSON 内容") from exc


def _local_verify(findings: list[Finding]) -> list[Finding]:
    verified: list[Finding] = []
    seen: set[tuple[str, int | None, str, str]] = set()
    for finding in findings:
        if not finding.evidence:
            continue
        if finding.confidence < 0.5:
            finding = finding.model_copy(update={"blocking": False})
        key = (finding.path, finding.line, finding.category, finding.problem)
        if key in seen:
            continue
        seen.add(key)
        verified.append(finding)
    return verified

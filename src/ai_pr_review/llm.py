from __future__ import annotations

import json
import os
import re
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
from ai_pr_review.schemas import ChunkAnalysis, CommentContext, Finding


class LLMError(RuntimeError):
    """Raised for user-facing LLM failures."""


@dataclass(frozen=True)
class LLMCallResult:
    payload: dict
    limitations: list[str] = field(default_factory=list)


COMMENT_DERIVED_MARKERS = (
    "已有评论",
    "评论摘要",
    "根据评论",
    "评论中",
    "copilot",
    "review comment",
    "review_comment",
    "issue comment",
    "issue_comment",
    "pull review",
    "pull_review",
    "comment summary",
    "comment_summary",
)


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
    comment_context: CommentContext | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    api_mode: str = "auto",
    timeout_seconds: float = 45.0,
    max_chunks: int | None = None,
    enabled: bool = True,
) -> tuple[list[Finding], list[str]]:
    if not enabled:
        return [], ["已按配置跳过 LLM 分析，仅输出规则引擎结果"]
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return [], ["未设置 OPENAI_API_KEY，已跳过 LLM 分析，仅输出规则引擎结果"]

    chunk_list = list(chunks)
    limitations: list[str] = []
    if max_chunks is not None and max_chunks >= 0 and len(chunk_list) > max_chunks:
        skipped = len(chunk_list) - max_chunks
        chunk_list = chunk_list[:max_chunks]
        limitations.append(f"LLM 分析已限制为前 {max_chunks} 个 chunk，跳过 {skipped} 个 chunk")

    findings: list[Finding] = []
    dropped_path_findings = 0
    dropped_comment_findings = 0
    client = _create_client(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    for chunk in chunk_list:
        try:
            analysis, call_limitations = _analyze_chunk(
                client,
                model=model,
                pr_summary=pr_summary,
                chunk=chunk,
                context=context,
                comments_summary=(
                    comment_context.as_prompt_text(chunk.path)
                    if comment_context is not None
                    else comments_summary
                ),
                api_mode=api_mode,
            )
            limitations.extend(call_limitations)
        except LLMError as exc:
            limitations.append(str(exc))
            continue
        kept_findings = []
        for finding in analysis.findings:
            if finding.path != chunk.path:
                dropped_path_findings += 1
                continue
            if _is_comment_derived_finding(finding):
                dropped_comment_findings += 1
                continue
            kept_findings.append(finding)
        findings.extend(
            finding.model_copy(update={"source": "llm", "rule_id": None})
            for finding in kept_findings
        )
    if dropped_path_findings:
        limitations.append(f"已丢弃 {dropped_path_findings} 条非当前文件 finding")
    if dropped_comment_findings:
        limitations.append(f"已丢弃 {dropped_comment_findings} 条仅由已有评论支撑的 finding")
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
        and finding.source != "rule"
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
        if finding.source != "rule" and finding in high_risk and key not in verified_keys:
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

    try:
        return LLMCallResult(payload=_parse_json_object(text), limitations=limitations)
    except LLMError:
        if limitations:
            raise
        limitations.append("Chat Completions 返回非标准 JSON，已尝试从文本中提取 JSON")
        try:
            text = _call_chat_once(
                client,
                model=model,
                system=system,
                user=user,
                use_response_format=False,
            )
            return LLMCallResult(payload=_parse_json_object(text), limitations=limitations)
        except Exception as exc:
            raise LLMError(f"Chat Completions 返回了不可解析 JSON: {exc}") from exc


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
            {"role": "user", "content": _chat_user_prompt(user)},
        ],
        "temperature": 0,
    }
    if use_response_format:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    text = _chat_response_text(response)
    if not text:
        raise LLMError("Chat Completions 未返回可解析文本")
    return text


def _response_output_text(response: object) -> str | None:
    text = getattr(response, "output_text", None)
    if text:
        return str(text)
    try:
        output = getattr(response, "output")
        parts: list[str] = []
        for item in output:
            for content in getattr(item, "content", []):
                value = _extract_text(content)
                if value:
                    parts.append(value)
        return "\n".join(parts) if parts else None
    except Exception:
        return None


def _chat_response_text(response: object) -> str | None:
    direct_text = _extract_text(response)
    if direct_text:
        return direct_text

    if isinstance(response, dict):
        output_text = _extract_text(response.get("output_text"))
        if output_text:
            return output_text
        choices = response.get("choices")
        if isinstance(choices, list):
            parts: list[str] = []
            for choice in choices:
                if not isinstance(choice, dict):
                    text = _extract_text(choice)
                    if text:
                        parts.append(text)
                    continue
                message = choice.get("message")
                if isinstance(message, dict):
                    message_text = _extract_text(message.get("content"))
                    if message_text:
                        parts.append(message_text)
                    message_text = _extract_text(message.get("text"))
                    if message_text:
                        parts.append(message_text)
                choice_text = _extract_text(choice.get("text"))
                if choice_text:
                    parts.append(choice_text)
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    delta_text = _extract_text(delta.get("content"))
                    if delta_text:
                        parts.append(delta_text)
            if parts:
                return "\n".join(parts)
        return None

    output_text = _extract_text(getattr(response, "output_text", None))
    if output_text:
        return output_text
    choices = getattr(response, "choices", None)
    if choices:
        parts: list[str] = []
        for choice in choices:
            message = getattr(choice, "message", None)
            if message is not None:
                content = _extract_text(getattr(message, "content", None))
                if content:
                    parts.append(content)
                message_text = _extract_text(getattr(message, "text", None))
                if message_text:
                    parts.append(message_text)
            choice_text = _extract_text(getattr(choice, "text", None))
            if choice_text:
                parts.append(choice_text)
            delta = getattr(choice, "delta", None)
            if delta is not None:
                delta_text = _extract_text(getattr(delta, "content", None))
                if delta_text:
                    parts.append(delta_text)
        if parts:
            return "\n".join(parts)
    return None


def _extract_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("text", "content", "output_text"):
            text = _extract_text(value.get(key))
            if text:
                parts.append(text)
        return "\n".join(parts) if parts else None
    if isinstance(value, list):
        parts = []
        for item in value:
            text = _extract_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts) if parts else None
    for attr in ("text", "content", "output_text"):
        try:
            text = _extract_text(getattr(value, attr))
        except Exception:
            continue
        if text:
            return text
    return None


def _chat_user_prompt(user: str) -> str:
    schema = json.dumps(CHUNK_ANALYSIS_JSON_SCHEMA, ensure_ascii=False)
    return (
        f"{user}\n\n"
        "请只输出一个 JSON 对象，不要输出 Markdown、解释、代码块或额外文字。"
        "JSON 必须符合以下 schema：\n"
        f"{schema}"
    )


def _parse_json_object(text: str) -> dict:
    text = text.strip()
    if not text:
        raise LLMError("LLM 返回空文本")
    if _looks_like_html(text):
        raise LLMError(
            "LLM 返回了 HTML 页面，OPENAI_BASE_URL 可能配置成了管理后台或网页根地址；"
            "请改为兼容 OpenAI API 的 endpoint，通常以 /v1 结尾"
        )
    for candidate in _json_candidates(text):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise LLMError("LLM 返回内容不是可解析 JSON 对象")


def _looks_like_html(text: str) -> bool:
    lowered = text[:500].lstrip().lower()
    return lowered.startswith("<!doctype html") or lowered.startswith("<html")


def _json_candidates(text: str) -> list[str]:
    candidates = [text]
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        candidates.append(fence_match.group(1))
    extracted = _extract_first_json_object(text)
    if extracted:
        candidates.append(extracted)
    return candidates


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _create_client(
    *,
    api_key: str,
    base_url: str | None = None,
    timeout_seconds: float = 45.0,
) -> OpenAI:
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
    return OpenAI(api_key=api_key, timeout=timeout_seconds)


def _is_comment_derived_finding(finding: Finding) -> bool:
    text = "\n".join([*finding.evidence, finding.problem, finding.suggestion]).lower()
    return any(marker.lower() in text for marker in COMMENT_DERIVED_MARKERS)


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

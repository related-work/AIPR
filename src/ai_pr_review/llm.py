from __future__ import annotations

import json
import os
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


def select_models(config: ReviewConfig, profile: str) -> tuple[str, str]:
    fast = os.getenv("OPENAI_FAST_MODEL") or config.models.fast
    strong = os.getenv("OPENAI_STRONG_MODEL") or config.models.strong
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
) -> tuple[list[Finding], list[str]]:
    if not os.getenv("OPENAI_API_KEY"):
        return [], ["未设置 OPENAI_API_KEY，已跳过 LLM 分析，仅输出规则引擎结果"]

    findings: list[Finding] = []
    limitations: list[str] = []
    client = OpenAI()
    for chunk in chunks:
        try:
            analysis = _analyze_chunk(
                client,
                model=model,
                pr_summary=pr_summary,
                chunk=chunk,
                context=context,
                comments_summary=comments_summary,
            )
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
) -> tuple[list[Finding], list[str]]:
    high_risk = [
        finding
        for finding in findings
        if finding.severity in {"critical", "high"} and finding.confidence >= 0.75
    ]
    if not high_risk or not os.getenv("OPENAI_API_KEY"):
        return _local_verify(findings), []

    client = OpenAI()
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
        )
        verified = ChunkAnalysis.model_validate(response).findings
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
) -> ChunkAnalysis:
    payload = _call_structured(
        client,
        model=model,
        system=REVIEW_SYSTEM_PROMPT,
        user=build_chunk_prompt(
            pr_summary=pr_summary,
            chunk=chunk,
            context=context,
            comments_summary=comments_summary,
        ),
    )
    try:
        return ChunkAnalysis.model_validate(payload)
    except ValidationError as exc:
        raise LLMError(f"LLM 返回结构不符合 schema: {exc}") from exc


def _call_structured(client: OpenAI, *, model: str, system: str, user: str) -> dict:
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

    text = getattr(response, "output_text", None)
    if not text:
        try:
            text = response.output[0].content[0].text
        except Exception as exc:
            raise LLMError("OpenAI Responses API 未返回可解析文本") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("OpenAI Responses API 返回了非 JSON 内容") from exc


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
